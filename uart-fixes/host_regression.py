"""Compile and run real source-extracted Miot loop and actual Arduino ring, offline.
Usage: python3 host_regression.py CANDIDATE [ring|timeout|all]
No network or device access; generated C++ and executables live in CANDIDATE.parent/tests.
"""
import pathlib, subprocess, sys, re
root=pathlib.Path(sys.argv[1]);which=sys.argv[2] if len(sys.argv)>2 else 'all'
cpp=(root/'components/miot/miot.cpp').read_text()
loop=cpp[cpp.index('void Miot::loop() {'):cpp.index('\nvoid Miot::dump_config()')]
serial=(root/'libretiny/cores/realtek-ambz2/arduino/libraries/Serial/SerialPrivate.h').read_text()
ringtype=re.search(r'(RingBuffer(?:N<\d+>)?)\s+buf;',serial).group(1)
pre=r'''
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <deque>
#include <string>
#include <vector>
#include <cassert>
#include "RingBuffer.h"
uint32_t now_ms;
uint32_t millis(){return now_ms;}
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGV(...) ((void)0)
constexpr const char *TAG="miot";
constexpr int RECEIVE_TIMEOUT=300;
struct Miot {
 static constexpr size_t MAX_LINE_LENGTH=512;
 uint8_t rx_message_[513]{};
 size_t rx_count_=0;
 uint32_t last_rx_char_timestamp_=0;
 std::deque<uint8_t> fifo;
 std::vector<std::string> messages;
 bool available(){return !fifo.empty();}
 bool read_byte(uint8_t *c){*c=fifo.front();fifo.pop_front();return true;}
 void feed(const std::string&s){for(auto c:s)fifo.push_back(c);}
 void process_message_(){messages.emplace_back((char*)rx_message_,rx_count_);}
 std::string get_printable_rx_message(){return {};}
 void loop();
};
'''
ring=r'''
void test_ring(){
 const std::string poll="result 2 1 0 false 2 2 0 0 2 5 0 2 2 6 0 70 2 8 0 0 3 1 0 50 3 7 0 24 5 1 0 false 6 1 0 false\r";
 ActualRing ring;for(auto c:poll)ring.store_char(c);
 std::string received;while(ring.available()) received+=(char)ring.read_char();
 printf("poll burst: sent=%zu retained=%zu\n",poll.size(),received.size());fflush(stdout);
 assert(received==poll);
 // Boundary and wraparound of actual RingBufferN implementation.
 for(int i=0;i<512;i++)ring.store_char('a');assert(ring.available()==512);
 for(int i=0;i<300;i++)assert(ring.read_char()=='a');
 for(int i=0;i<300;i++)ring.store_char('b');assert(ring.available()==512);
 for(int i=0;i<212;i++)assert(ring.read_char()=='a');
 for(int i=0;i<300;i++)assert(ring.read_char()=='b');
 assert(ring.available()==0);puts("PASS ring burst, capacity, wraparound");
}
'''
timeout=r'''
void test_timeout(){
 Miot m;now_ms=0;m.feed("get_down");m.loop();
 now_ms=350;m.feed("\r");m.loop();
 printf("queued CR after 350ms: messages=%zu content=%s\n",m.messages.size(),m.messages.empty()?"<none>":m.messages[0].c_str());fflush(stdout);
 assert(m.messages.size()==1 && m.messages[0]=="get_down");
 puts("PASS queued CR survives delayed main loop");
}
void test_others(){
 Miot m;now_ms=0;m.feed("stale");m.loop();now_ms=350;m.loop();
 assert(m.rx_count_==0);m.feed("fresh\r");m.loop();assert(m.messages.size()==1 && m.messages[0]=="fresh");
 puts("PASS timeout still drops stale partial with empty UART");
 Miot n;now_ms=0;n.feed("get_");n.loop();now_ms=100;n.feed("down\rnext\r");n.loop();n.loop();
 assert(n.messages.size()==2 && n.messages[0]=="get_down" && n.messages[1]=="next");
 puts("PASS normal fragmentation and consecutive frames");
 Miot u;now_ms=0xfffffff0;u.feed("wrap");u.loop();now_ms=0x20;u.loop();assert(u.rx_count_==4);
 now_ms=0x200;u.loop();assert(u.rx_count_==0);puts("PASS millis wraparound");
 Miot z;now_ms=0;z.feed(std::string(513,'x')+"\r");z.loop();assert(z.messages.size()==1 && z.messages[0]=="x");
 puts("PASS existing overlength behavior preserved");
}
'''
main={'ring':'test_ring();','timeout':'test_timeout();','all':'test_ring();test_timeout();test_others();'}[which]
out=root.parent/'tests';out.mkdir(exist_ok=True)
src=out/('host_'+which+'.cpp');binary=src.with_suffix('')
src.write_text(pre+'\nusing ActualRing=arduino::'+ringtype+';\n'+loop+ring+timeout+'\nint main(){'+main+'}\n')
subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Wno-unused-variable','-Wno-misleading-indentation','-iquote'+str(root/'pio-home/packages/framework-arduino-api/api'),str(src),'-o',str(binary)],check=True)
subprocess.run([str(binary)],check=True)
