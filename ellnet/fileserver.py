
# Copyright (c) 2012 J. David Lee. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without 
# modification, are permitted provided that the following conditions are
# met:
#
#    1. Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#
#    2. Redistributions in binary form must reproduce the above
#       copyright notice, this list of conditions and the following
#       disclaimer in the documentation and/or other materials provided
#       with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDERS OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
# OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
# TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
# USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.

import os
import time
import threading
import struct

import ellnet


TCP_PORT = 11008
UDP_PORT = 11009

PKT_ADVERT       = 0
PKT_LISTING_REQ  = 1
PKT_READ_FILE    = 2


###############################################################################
# File server. 
###############################################################################
class FileServer(ellnet.EllNetBaseServer):
    def __init__(self, dev, name, msg, share_dir, advert_interval=8):
        self._lock = threading.Lock()
        
        self._dev = dev
        
        # Remove trailing slash from shared directory. 
        self.set_name(name)
        self.set_msg(msg)
        self.set_share_dir(share_dir)

        self._advert_interval = advert_interval

        self._hosts = {} # Map from address to (name, msg, last_seen).
        
        self._req_handlers = {
            PKT_LISTING_REQ  : self._handle_listing_req,
            PKT_READ_FILE    : self._handle_read
            }
        
        self._bc_handlers = {
            PKT_ADVERT : self._handle_advert
            }

        self._read_struct = struct.Struct('=QQ')

        ellnet.EllNetBaseServer.__init__(self, dev, TCP_PORT, UDP_PORT)
        
        # Start advert thread. 
        th = threading.Thread(target=self._advertiser)
        th.daemon = True
        th.start()


    ##################################################################
    # Access to protected data. 
    ##################################################################
    def get_name(self):
        with self._lock:
            return self._name
        

    def set_name(self, name):
        with self._lock:
            self._name = name
        
        
    def get_msg(self):
        with self._lock:
            return self._msg
    

    def set_msg(self, msg):
        with self._lock:
            self._msg = msg


    def get_share_dir(self):
        with self._lock:
            return self._share_dir
        

    def set_share_dir(self, dir_):
        while len(dir_) > 0 and dir_[-1] == '/':
            dir_ = dir_[:-1]

        with self._lock:
            self._share_dir = dir_


    def get_full_path(self, path):
        with self._lock:
            return self._share_dir + path


    def _update_host(self, addr, name, msg):
        with self._lock:
            self._hosts[addr] = (name, msg, time.time())
            

    def get_hosts(self):
        """Return a list of tuples (addr, name, msg, age)."""
        now = time.time()
        with self._lock:
            ret = []
            for addr, (name, msg, last_seen) in self._hosts.iteritems():
                ret.append((addr, name, msg, now - last_seen))
                
        return ret


    def get_host(self, addr):
        """Give an address, return (name, message, age)."""
        now = time.time()
        with self._lock:
            if addr in self._hosts:
                name, msg, last_seen = self._hosts[addr]
                return name, msg, now - last_seen
            else:
                return None, None, None

    
    def purge_hosts(self, age):
        """Remove hosts older than the given age in seconds."""
        with self._lock:
            now = time.time()
            for addr in self._hosts.keys():
                if now - self._hosts[addr][2] > age:
                    del self._hosts[addr]


    ##################################################################
    # Adverts.
    ##################################################################
    def _advertiser(self):
        while 1:
            msg  = self.get_msg()
            name = self.get_name()
            data = '\0'.join((name, msg)).encode('utf8')
            self._send_broadcast_packet(PKT_ADVERT, data)
            time.sleep(self._advert_interval)

    
    def _handle_advert(self, addr, port, data):
        name, msg = data.split('\0')
        self._update_host(addr, name, msg)


    ##################################################################
    # Listing request. 
    ##################################################################
    def get_listing(self, addr, path):
        path = path.encode('utf8')

        sock = ellnet.init_request(
            self._dev, addr, TCP_PORT, PKT_LISTING_REQ, path)

        data = ellnet.recv_block(sock).decode('utf8')
        strs = data.split('\0')
        
        dirs, files = [], []
        for i in range(0, len(strs), 2):
            name = strs[i]
            size = int(strs[i + 1])

            if size == -1:
                dirs.append(name)
            else:
                files.append((name, size))
                
        return dirs, files
    
    
    def _handle_listing_req(self, sock, req_data):
        path = self.get_full_path(req_data.decode('utf8'))
        
        strs = []
        for fn in os.listdir(path):
            file_path = os.path.join(path, fn)
            if os.path.isdir(file_path):
                size = "-1"
            elif os.path.isfile(file_path):
                size = str(os.path.getsize(file_path))
            else:
                continue

            strs.extend((fn, size))

        data = '\0'.join(strs).encode('utf8')
        ellnet.send_block(sock, data)
        

    ##################################################################
    # File transfers. 
    ##################################################################
    def read(self, addr, rpath, size, offset):
        req_data = self._read_struct.pack(size, offset) + rpath
        
        sock = ellnet.init_request(self._dev, 
                                   addr, 
                                   TCP_PORT,
                                   PKT_READ_FILE,
                                   req_data)
        
        return ellnet.recv_block(sock)


    
    def _handle_read(self, sock, req_data):
        size, offset = self._read_struct.unpack(req_data[:16])
        path = self.get_full_path(req_data[16:].decode('utf8'))
        
        with open(path, 'rb') as f:
            f.seek(offset)
            ellnet.send_block(sock, f.read(size))
                                  

