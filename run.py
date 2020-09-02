#!/usr/bin/python
"""
Based on:
=================================================================================
Author: JP Meijers
Date: 2017-02-26
Based on: https://github.com/rayozzie/ttn-resin-gateway-rpi/blob/master/run.sh
2019-11-08: Modified by pe1mew to add GW_LOGGER and GW_AUTOQUIT_THRESHOLD
=================================================================================
2020-09-01 Code clean up and rewrite to work with Helium, RAK833 and PiSupply HAT 
github.com/dansku - https://www.danielandrade.net
"""

import os
import os.path
import sys
import urllib2
import time
import uuid
import json
import subprocess
try:
  import RPi.GPIO as GPIO
except RuntimeError:
  print("Error importing RPi.GPIO!  This is probably because you need superuser privileges.  You can achieve this by using 'sudo' to run your script")

GWID_PREFIX="FFFE"

if not os.path.exists("/opt/ttn-gateway/mp_pkt_fwd"):
  print ("ERROR: gateway executable not found. Is it built yet?")
  sys.exit(0)

if os.environ.get('HALT') != None:
  print ("*** HALT asserted - exiting ***")
  sys.exit(0)

# # Show info about the machine we're running on
# print ("*** Resin Machine Info:")
# print ("*** Type: "+str(os.environ.get('RESIN_MACHINE_NAME')))
# print ("*** Arch: "+str(os.environ.get('RESIN_ARCH')))

# if os.environ.get("RESIN_HOST_CONFIG_core_freq")!=None:
#   print ("*** Core freq: "+str(os.environ.get('RESIN_HOST_CONFIG_core_freq')))

# if os.environ.get("RESIN_HOST_CONFIG_dtoverlay")!=None:
#   print ("*** UART mode: "+str(os.environ.get('RESIN_HOST_CONFIG_dtoverlay')))

# Check if the correct environment variables are set

print ("*******************")
print ("*** Configuration:")
print ("*******************")

if os.environ.get("GW_EUI")==None:
  # The FFFE should be inserted in the middle (so xxxxxxFFFExxxxxx)
  my_eui = format(uuid.getnode(), '012x')
  my_eui = my_eui[:6]+GWID_PREFIX+my_eui[6:]
  my_eui = my_eui.upper()
else:
  my_eui = os.environ.get("GW_EUI")

print ("GW_EUI:\t"+my_eui)

# Define default configs
latitude = os.getenv('GW_REF_LATITUDE', 0)
longitude = os.getenv('GW_REF_LONGITUDE', 0)
altitude = os.getenv('GW_REF_ALTITUDE', 0)
frequency_plan_url = os.getenv('FREQ_PLAN_URL', "https://account.thethingsnetwork.org/api/v2/frequency-plans/EU_863_870")

print ("Latitude:\t\t"+str(latitude))
print ("Longitude:\t\t"+str(longitude))
print ("Altitude:\t\t"+str(altitude))
print ("Gateway EUI:\t"+my_eui)
print ("Has hardware GPS:\t"+str(os.getenv('GW_GPS', False)))

# Retrieve global_conf #just use the damn file
sx1301_conf = {}
try:
  response = urllib2.urlopen(frequency_plan_url, timeout=30)
  global_conf = response.read()
  global_conf_object = json.loads(global_conf)
  if('SX1301_conf' in global_conf_object):
    sx1301_conf = global_conf_object['SX1301_conf']
except urllib2.URLError as err: 
  print ("Unable to fetch global conf from Github")
  sys.exit(0)

sx1301_conf['antenna_gain'] = float(os.getenv('GW_ANTENNA_GAIN', 0))

# Build local_conf
gateway_conf = {}
gateway_conf['gateway_ID'] = my_eui
gateway_conf['contact_email'] = os.getenv('GW_CONTACT_EMAIL', "")
gateway_conf['stat_file'] = 'loragwstat.json'
gateway_conf['push_timeout_ms'] = int(os.getenv("GW_PUSH_TIMEOUT", 100)) # Default in code is 100

if(os.getenv('GW_LOGGER', "false")=="true"):
  gateway_conf['logger'] = True
else:
  gateway_conf['logger'] = False

if(os.getenv('GW_FWD_CRC_ERR', "false")=="true"):
  #default is False
  gateway_conf['forward_crc_error'] = True

if(os.getenv('GW_FWD_CRC_VAL', "true")=="false"):
  #default is True
  gateway_conf['forward_crc_valid'] = False

if(os.getenv('GW_DOWNSTREAM', "true")=="false"):
  #default is True
  gateway_conf['downstream'] = False

# Parse GW_GPS env var. It is a string, we need a boolean.
if(os.getenv('GW_GPS', "false")=="true"):
  gw_gps = True
else:
  gw_gps = False

# Use hardware GPS
if(gw_gps):
  print ("Using real GPS")
  gateway_conf['gps'] = True
  gateway_conf['fake_gps'] = False
  gateway_conf['gps_tty_path'] = os.getenv('GW_GPS_PORT', "/dev/ttyAMA0")
# Use fake GPS with coordinates from TTN
elif(gw_gps==False and latitude!=0 and longitude!=0):
  print ("Using fake GPS")
  gateway_conf['gps'] = True
  gateway_conf['fake_gps'] = True
  gateway_conf['ref_latitude'] = float(latitude)
  gateway_conf['ref_longitude'] = float(longitude)
  gateway_conf['ref_altitude'] = float(altitude)
# No GPS coordinates
else:
  print ("Not sending coordinates")
  gateway_conf['gps'] = False
  gateway_conf['fake_gps'] = False

# Log all LoRaWAN packets to console
if(os.getenv('GW_LOGGER', "false")=="true"):
  gateway_conf['logger'] = True
  print ("Packet logging enabled")

# Autoquit when a number of PULL_ACKs have been missed
autoquit_threshold = int(os.getenv('GW_AUTOQUIT_THRESHOLD', 0))
if(autoquit_threshold > 0):
  gateway_conf['autoquit_threshold'] = int(os.getenv('GW_AUTOQUIT_THRESHOLD', 5))
  print ("Autoquit after", gateway_conf['autoquit_threshold'], "missed PULL_ACKs")

# Add server configuration
gateway_conf['servers'] = []

# Add server
server = {}
server['server_address'] = os.environ.get("SERVER_ADDRESS")
server['serv_port_up'] = int(os.getenv("SERVER_PORTUP", 1700))
server['serv_port_down'] = int(os.getenv("SERVER_PORTDOWN", 1700))
server['serv_enabled'] = True

gateway_conf['servers'].append(server)

# We merge the json objects from the global_conf and local_conf and save it to the global_conf.
# Therefore there will not be a local_conf.json file.
local_conf = {'SX1301_conf': sx1301_conf, 'gateway_conf': gateway_conf}
with open('/opt/ttn-gateway/global_conf.json', 'w') as the_file:
  the_file.write(json.dumps(local_conf, indent=4))

# Endless loop to reset and restart packet forwarder
while True:
  # Reset the gateway board - this only works for the Raspberry Pi.
  GPIO.setmode(GPIO.BOARD) # hardware pin numbers, just like gpio -1

  if (os.environ.get("GW_RESET_PIN")!=None):
    try:
      pin_number = int(os.environ.get("GW_RESET_PIN"))
      print ("[TTN Gateway]: Resetting concentrator on pin "+str(os.environ.get("GW_RESET_PIN")))
      GPIO.setup(pin_number, GPIO.OUT, initial=GPIO.LOW)
      GPIO.output(pin_number, 0)
      time.sleep(0.1)
      GPIO.output(pin_number, 1)
      time.sleep(0.1)
      GPIO.output(pin_number, 0)
      time.sleep(0.1)
      GPIO.input(pin_number)
      GPIO.cleanup(pin_number)
      time.sleep(0.1)
    except ValueError:
      print ("Can't interpret "+os.environ.get("GW_RESET_PIN")+" as a valid pin number.")

  else:
    print ("[TTN Gateway]: Resetting concentrator on default pin 22.")
    GPIO.setup(22, GPIO.OUT, initial=GPIO.LOW)
    GPIO.output(22, 0)
    time.sleep(0.1)
    GPIO.output(22, 1)
    time.sleep(0.1)
    GPIO.output(22, 0)
    time.sleep(0.1)
    GPIO.input(22)
    GPIO.cleanup(22)
    time.sleep(0.1)

  # Start forwarder
  subprocess.call(['/opt/ttn-gateway/mp_pkt_fwd', '-c', '/opt/ttn-gateway/', '-s', os.getenv('SPI_SPEED', '8000000')])
  time.sleep(15)
