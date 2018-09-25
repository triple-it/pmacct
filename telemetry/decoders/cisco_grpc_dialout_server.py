#!/usr/bin/env python
#
#   pmacct (Promiscuous mode IP Accounting package)
#   pmacct is Copyright (C) 2003-2018 by Paolo Lucente
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#

from concurrent import futures
import sys, getopt
import ujson as json
import zmq
import time

# gRPC and Protobuf imports
import grpc
from google.protobuf.json_format import MessageToJson
from google.protobuf.json_format import MessageToDict
import cisco_grpc_dialout_pb2
import cisco_grpc_dialout_pb2_grpc
import cisco_telemetry_pb2
import cisco_ifstatsbag_generic_pb2

_ONE_DAY_IN_SECONDS = 60 * 60 * 24

zmqContext = None
zmqSock = None

class gRPCMdtDialoutServicer(cisco_grpc_dialout_pb2_grpc.gRPCMdtDialoutServicer):
	def __init__(self):
		print "Initializing gRPCMdtDialoutServicer()"

	def MdtDialout(self, message, context):
		grpcPeerStr = context.peer() 

		grpcPeer = {}
		(grpcPeerProto, grpcPeer['telemetry_node'], grpcPeer['telemetry_node_port']) = grpcPeerStr.split(":")
		grpcPeer['telemetry_node_vendor'] = "Cisco"
		jsonTelemetryNode = json.dumps(grpcPeer)

		for new_msg in message:
			telemetry_msg = cisco_telemetry_pb2.Telemetry()
			telemetry_msg.ParseFromString(new_msg.data)
			jsonStrTelemetry = MessageToJson(telemetry_msg)
			dictTelemetry = json.loads(jsonStrTelemetry)

			(proto, path) = telemetry_msg.encoding_path.split(":")

			if (proto == "Cisco-IOS-XR-infra-statsd-oper"):
				for new_row in telemetry_msg.data_gpb.row:
					dictIfStats = {}

					ifStats_msg = cisco_ifstatsbag_generic_pb2.ifstatsbag_generic()
					ifStats_msg.ParseFromString(new_row.content)
					dictIfStatsContent = MessageToDict(ifStats_msg,
										including_default_value_fields = True,
										preserving_proto_field_name = True,
										use_integers_for_enums = True)

					dictIfStats['row'] = {}
					dictIfStats['row']['content'] = dictIfStatsContent
					dictIfStats['row']['timestamp'] = new_row.timestamp

					dictTelemetry['dataGpb'] = dictIfStats
					sendJsonTelemetryData(jsonTelemetryNode, dictTelemetry)
			else:
				sendJsonTelemetryData(jsonTelemetryNode, dictTelemetry)

def sendJsonTelemetryData(jsonTelemetryNode, dictTelemetryData):
	global zmqSock

	jsonTelemetryData = json.dumps(dictTelemetryData) 

	# XXX: debug code
	# print "dataPublish(): +++"
	# print "dataPublish(): " + jsonTelemetryNode
	# print "dataPublish(): " + jsonTelemetryData
	# print "dataPublish(): ---"

	if not zmqSock.closed:
		try:
			zmqSock.send("%s" % jsonTelemetryNode, flags=zmq.SNDMORE)
			zmqSock.send("%s" % jsonTelemetryData)
		except ZMQError:
			pass

def usage(tool):
	print ""
	print "Usage: %s [Args]" % tool
	print ""

	print "Optional Args:"
	print "  -h, --help".ljust(25) + "Print this help"
	print "  -g, --grpc-port".ljust(25) + "Set the port for input gRPC sessions [default: '10001']"
	print "  -Z, --zmq-host".ljust(25) + "Set the ZeroMQ host for output [default: '127.0.0.1']"
	print "  -z, --zmq-port".ljust(25) + "Set the ZeroMQ port for output [default: '50001']"

def serve():
	global zmqContext
	global zmqSock

	try:
		opts, args = getopt.getopt(sys.argv[1:], "hg:Z:z:", ["help", "grpc-port=", "zmq-host=", "zmq-port="])
	except getopt.GetoptError as err:
		print str(err)
		usage(sys.argv[0])
		sys.exit(1)

	# Defaults
	grpc_port = 10001
	zmq_host = "127.0.0.1"
	zmq_port = 50001

	for o, a in opts:
		if o in ("-h", "--help"):
			usage(sys.argv[0])
			sys.exit(0)
		elif o in ("-g", "--grpc-port"):
			grpc_port = a
		elif o in ("-Z", "--zmq-host"):
			zmq_host = a
		elif o in ("-z", "--zmq-port"):
			zmq_port = a
		else:
			assert False, "unhandled option"

	zmqBindStr = "tcp://" + zmq_host + ":" + str(zmq_port)
	gRPCBindStr = "[::]:" + str(grpc_port)

	zmqContext = zmq.Context()
	zmqSock = zmqContext.socket(zmq.PUSH)
	zmqSock.bind(zmqBindStr)

	gRPCserver = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
	cisco_grpc_dialout_pb2_grpc.add_gRPCMdtDialoutServicer_to_server(gRPCMdtDialoutServicer(), gRPCserver)
	gRPCserver.add_insecure_port(gRPCBindStr)
	gRPCserver.start()

	try:
		while True:
			time.sleep(_ONE_DAY_IN_SECONDS)
	except KeyboardInterrupt:
		gRPCserver.stop(0)

if __name__ == '__main__':
	serve()
