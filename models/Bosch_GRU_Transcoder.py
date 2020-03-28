#!/usr/bin/env python
import os

model_version = '012'
history_rows = 5
inputs = 71

if os.path.exists(os.path.expanduser('./models/gpu-model-%s.hdf5' % model_version)):
  model_name = 'gpu-model-%s' % model_version
else:
  os.environ["CUDA_VISIBLE_DEVICES"]="-1"
  model_name = 'cpu-model-%s' % model_version

import zmq
import time
import json
import platform 
import subprocess
import multiprocessing
from tensorflow.python.keras.models import load_model #, Model  #, Sequential
import numpy as np
import joblib
from selfdrive.services import service_list
from enum import Enum
from cffi import FFI
from setproctitle import setproctitle
from selfdrive.kegman_conf import kegman_conf

ffi = FFI()
ffi.cdef("long syscall(long number, ...);")
libc = ffi.dlopen(None)

def set_realtime_priority(level):
  if platform.machine() == "x86_64":
    NR_gettid = 186
  elif platform.machine() == "aarch64":
    NR_gettid = 178
  else:
    raise NotImplementedError
  tid = libc.syscall(NR_gettid)
  print("/n/n realtime priority = %d  %s  %s/n" %(level, NR_gettid, str(tid)))
  return subprocess.call(['chrt', '-f', '-p', str(level), str(tid)])

def dump_sock(sock, wait_for_one=False):
  if wait_for_one:
    sock.recv()
  while 1:
    try:
      sock.recv(zmq.NOBLOCK)
    except zmq.error.Again:
      break

setproctitle('transcoderd')
#set_realtime_priority(1)
ipaddress = "tcp://127.0.0.1"

context = zmq.Context.instance()
gernModelInputs = context.socket(zmq.SUB)
gernModelInputs.connect("tcp://127.0.0.1:%d" % service_list['model'].port)
gernModelInputs.setsockopt(zmq.SUBSCRIBE, b"")

gernModelOutputs = context.socket(zmq.PUB)
gernModelOutputs.bind("tcp://*:8605")

model = load_model(os.path.expanduser('./models/' + model_name + '.hdf5'))
model_input = np.zeros((history_rows, inputs))
fingerprint = np.array([[0,0,0,0,0]])
kegman = kegman_conf()  
if int(kegman.conf['fingerprint']) >= 0: 
  fingerprint[0,int(kegman.conf['fingerprint'])] = 1

model.predict_on_batch([[model_input[:,:8]], [model_input[:,8:11]], [model_input[-1:,-60:-32]], [fingerprint], [model_input[:,-32:-16]], [model_input[:,-16:]]])
frame = 0
dump_sock(gernModelInputs, True)

while 1:
  model_input_array = gernModelInputs.recv()

  input_list = json.loads(model_input_array)
  model_input = np.asarray(input_list[:-1]).reshape(history_rows, inputs)

  all_inputs = [[model_input[:,:-60-3]], [model_input[:,-60-3:-60]], [model_input[-1:,-60:-32]], [fingerprint], [model_input[:,-32:-16]], [model_input[:,-16:]]]

  model_output = list(model.predict_on_batch(all_inputs)[0].astype('float'))
  model_output.append(input_list[-1])
  gernModelOutputs.send_json(model_output)
  if frame % 30 == 0:
    print(fingerprint, frame, time.time())
  frame += 1