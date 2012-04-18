
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
import socket
import SocketServer
import threading
import struct


BCAST_ADDR = 'ff02::1'


###############################################################################
# Random numbers. 
###############################################################################
def rand_uint8():
    return struct.unpack('=B', os.urandom(1))[0]

def rand_uint16():
    return struct.unpack('=H', os.urandom(2))[0]

def rand_uint32():
    return struct.unpack('=I', os.urandom(4))[0]

def rand_uint64():
    return struct.unpack('=Q', os.urandom(8))[0]


###############################################################################
# Broadcast socket is a simple wrapper around a udp socket. 
###############################################################################
class BroadcastSocket(object):
    def __init__(self, dev, port, cb=None):
        """
        dev  -- The device to broadcast on. 
        port -- The port number to listen/receive on. 
        cb   -- Callback called when packets arrive. fn(addr, port, data). 
        """
        self.max_bytes = 16384
        self.port = port

        addr = '{0}%{1}'.format(BCAST_ADDR, dev)
        
        # Connect to the socket. 
        addrinfo = socket.getaddrinfo(
            addr, self.port, socket.AF_INET6, socket.SOCK_DGRAM)[0]

        (family, socktype, proto, canonname, sockaddr) = addrinfo
        
        self.sockaddr = sockaddr

        self._sock = socket.socket(family, socktype, proto)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        self._sock.bind(sockaddr)

        if cb is not None:
            self._cb = cb
            th = threading.Thread(target=self._socket_reader)
            th.daemon = True
            th.start()
            

    def send_broadcast(self, data):
        assert len(data) < self.max_bytes
        self._sock.sendto(data, (BCAST_ADDR, self.port))
            
            
    def _socket_reader(self):
        while 1:
            data = self._sock.recvfrom(self.max_bytes)
            data, (addr, port, junk1, junk2) = data
            addr = addr.split('%')[0]

            try:
                self._cb(addr, port, data)
            except Exception, ex:
                print('BroadcastSocket._socket_reader exception in callback:')
                print(ex)
    

###############################################################################
# LNet server base class. 
###############################################################################
class EllNetBaseServer(object):
    def __init__(self, dev, tcp_port, udp_port):
        self._dev      = dev
        self._tcp_port = tcp_port
        self._udp_port = udp_port

        # Create broadcast object. 
        self._broadcaster = BroadcastSocket(
            self._dev, udp_port, self._broadcast_handler)
        
        # Mapping from request type (uint16) to callback function. 
        # fn(sock, req_data)
        #self._req_handlers = {}
        
        # Mapping from request type (uint16) to callback for broadcast packets.
        # fn(addr, port, broadcast_data)
        #self._bc_handlers = {}
        
        # Create a handler for socket connectinos. 
        class ReqHandler(SocketServer.BaseRequestHandler):
            def handle(self_rh):
                sock = self_rh.request
                pkt_type, data = recv_request(sock)
                if pkt_type in self._req_handlers:
                    try:
                        self._req_handlers[pkt_type](sock, data)
                    except Exception, ex:
                        print('Exception in request handler:')
                        print(ex)

        # Create a threaded server. 
        class Server(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
            address_family = socket.AF_INET6
        
        server = Server(('::', tcp_port), ReqHandler)
        server.allow_reuse_address=True
        
        th = threading.Thread(target=server.serve_forever)
        th.daemon = True
        th.start()


    def _broadcast_handler(self, addr, port, data):
        # Ignore our own broadcasts. 
        pkt_type, n_bytes = struct.unpack('=HI', data[:6])
        data = data[6:]
        if pkt_type in self._bc_handlers:
            self._bc_handlers[pkt_type](addr, port, data)
                
                
    def _send_broadcast_packet(self, pkt_type, data):
        packet = struct.pack('=HI', pkt_type, len(data)) + data
        try:
            self._broadcaster.send_broadcast(packet)
        except Exception, ex:
            print('EllNetBaseServer: error sending broadcast packet:')
            print(ex)


###############################################################################
# Functions for sending packets and data.
###############################################################################
_req_struct = struct.Struct('=HI')

def recv_request(sock):
    pkt_type, n_bytes = _req_struct.unpack(sock.recv(6))
    data = sock.recv(n_bytes)
    assert n_bytes == len(data)
    return pkt_type, data


def init_request(dev, addr, port, pkt_type, req_data):
    """Send the initial request packet to the address.
    
    Return: socket object. 
    """
    # Append the device to the address. 
    addr = '%'.join([addr, dev])
    
    # Connect to the socket. 
    addrinfo = socket.getaddrinfo(
        addr, port, socket.AF_INET6, socket.SOCK_STREAM)[0]
    
    (family, socktype, proto, canonname, sockaddr) = addrinfo
    
    sock = socket.socket(family, socktype, proto)
    sock.connect(sockaddr)
    
    packet = _req_struct.pack(pkt_type, len(req_data)) + req_data
    sock.sendall(packet)
    
    return sock


_blk_struct = struct.Struct('=I')

def send_block(sock, data):
    n_bytes = len(data)
    sock.sendall(_blk_struct.pack(n_bytes) + data)


def recv_bytes(sock, n):
    data_list = []
    recvd = 0
    while recvd < n:
        data = sock.recv(n - recvd)
        if len(data) == 0:
            raise Exception('Socket closed.')

        recvd += len(data)
        data_list.append(data)

    return ''.join(data_list)
    
    
def recv_block(sock):
    n_bytes = _blk_struct.unpack(recv_bytes(sock, 4))[0]
    data = recv_bytes(sock, n_bytes)
    return data
