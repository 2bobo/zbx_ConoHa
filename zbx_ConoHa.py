# coding: UTF-8
import os
import sys
import json
import ConfigParser
import requests
import socket
import struct
import time
from datetime import datetime

class ZabbixSender:
    zbx_header = 'ZBXD'
    zbx_version = 1
    zbx_sender_data = {u'request': u'sender data', u'data': []}
    send_data = ''

    def __init__(self, server_host, server_port = 10051):
        self.server_ip = socket.gethostbyname(server_host)
        self.server_port = server_port

    def AddData(self, host, key, value, clock = None):
        add_data = {u'host': host, u'key': key, u'value': value}
        if clock != None:
            add_data[u'clock'] = clock
        self.zbx_sender_data['data'].append(add_data)
        return self.zbx_sender_data

    def ClearData(self):
        self.zbx_sender_data['data'] = []
        return self.zbx_sender_data

    def __MakeSendData(self):
        zbx_sender_json = json.dumps(self.zbx_sender_data, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        json_byte = len(zbx_sender_json)
        self.send_data = struct.pack("<4sBq" + str(json_byte) + "s", self.zbx_header, self.zbx_version, json_byte, zbx_sender_json)

    def Send(self):
        self.__MakeSendData()
        so = socket.socket()
        so.connect((self.server_ip, self.server_port))
        wobj = so.makefile(u'wb')
        wobj.write(self.send_data)
        wobj.close()
        robj = so.makefile(u'rb')
        recv_data = robj.read()
        robj.close()
        so.close()
        tmp_data = struct.unpack("<4sBq" + str(len(recv_data) - struct.calcsize("<4sBq")) + "s", recv_data)
        recv_json = json.loads(tmp_data[3])
        return recv_data


if __name__ == '__main__':
    base = os.path.dirname(os.path.abspath(__file__))
    config_file_path = os.path.normpath(os.path.join(base, 'config.ini'))

    conf = ConfigParser.SafeConfigParser()
    conf.read(config_file_path)

    # zabbix sender
    sender = ZabbixSender(conf.get("zabbix","ip"))

    # auth
    url = conf.get("ConoHa","Identity_Service_URL") + "/tokens"
    api_user = conf.get("ConoHa","API_user")
    api_pass = conf.get("ConoHa","API_pass")
    tenant_id = conf.get("ConoHa","tenantId")

    data = json.dumps({"auth":{"passwordCredentials":{"username":api_user ,"password":api_pass},"tenantId":tenant_id}})
    auth_header = {"Accept":"application/json"}
    response = requests.post(
        url,
        data=data,
        headers=auth_header)
    rdata = response.json()
    token_id = str(rdata["access"]["token"]["id"])

    def get_conoha_api(url, tokenid, data = ""):
        header = {"Accept":"application/json", "X-Auth-Token":token_id}
        response = requests.get(
            url,
            headers=header,
            data=data)
        return response.json()

    # get vmlist
    vmlist_url = "https://compute.tyo1.conoha.io/v2/" + tenant_id + "/servers/detail"
    rdata = get_conoha_api(vmlist_url, tenant_id)
    now_time = str(int(time.time()))
    servers = []
    data = []
    for server in rdata["servers"]:
        # VPS Server ID
        serverid = server["id"]
        servers.append({"id":server["id"], "nametag":server["metadata"]["instance_name_tag"]})
        data.append({"{#HOSTID}":server["id"], "{#HOSTNAME}":server["metadata"]["instance_name_tag"]})
        # VPS Status
        sender.AddData(serverid, "ConoHa.vm.status", server["OS-EXT-STS:power_state"])
        # VPS IP
        sender.AddData(serverid, "ConoHa.vm.extip", server["name"].replace("-", "."))
        # VPS CPU Performance
        vm_cpu_url = "https://compute.tyo1.conoha.io/v2/" + tenant_id + "/servers/" + server["id"] + "/rrd/cpu?start_date_raw=" + now_time + "&end_date_raw=" + now_time + "&mode=average"
        c = get_conoha_api(vm_cpu_url, tenant_id)
        sender.AddData(serverid, "ConoHa.vm.cpupfo", c["cpu"]["data"][0][0])

    paiment_url = "https://account.tyo1.conoha.io/v1/" + tenant_id + "/billing-invoices?limit=1&offset=1"
    rdata = get_conoha_api(paiment_url, tenant_id)
    invoice_date = datetime.strptime(rdata["billing_invoices"][0]["invoice_date"], "%Y-%m-%dT%H:%M:%SZ")
    # host
    send_data = json.dumps({"data":data})
    sender.AddData("ConoHa", "ConoHa.Hosts", send_data)
    # payment
    argvs = sys.argv
    if len(argvs) == 2 and argvs[1] == "payment":
        sender.AddData("ConoHa", "ConoHa.billing-invoices", int(rdata["billing_invoices"][0]["bill_plus_tax"]), int(time.mktime(invoice_date.timetuple())))
    # send
    sender.Send()
    sender.ClearData()

