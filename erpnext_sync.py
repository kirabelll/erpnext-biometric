# Configuration settings
# cspell:ignore ERPNEXT

# ERPNext related configs
ERPNEXT_API_KEY = ' 212d6c8a4b3b6b8'
ERPNEXT_API_SECRET = 'fd4eab948b04db1'
ERPNEXT_URL = 'http://172.16.10.81'
ERPNEXT_VERSION = 14

# operational configs
PULL_FREQUENCY = 1  # in minutes (reduced frequency to avoid spam)
LOGS_DIRECTORY = 'logs'  # logs of this script is stored in this directory
IMPORT_START_DATE = None  # format: '20190501'

# Time synchronization configs
SYNC_DEVICE_TIME = True  # Enable automatic time synchronization
MAX_TIME_DIFFERENCE = 300  # Maximum allowed time difference in seconds (5 minutes)
SYNC_TIME_ON_STARTUP = True  # Sy nc time when service starts

# Biometric device configs (all keys mandatory, except latitude and longitude they are mandatory only if 'Allow Geolocation Tracking' is turned on in Frappe HR)
    #- device_id - must be unique, strictly alphanumerical chars only. no space allowed.
    #- ip - device IP Address
    #- punch_direction - 'IN'/'OUT'/'AUTO'/None
    #- clear_from_device_on_fetch: if set to true then attendance is deleted after fetch is successful.
                                    #(Caution: this feature can lead to data loss if used carelessly.)
    #- latitude - float, latitude of the location of the device
    #- longitude - float, longitude of the location of the device
devices = [
    {'device_id':'Machine_4','ip':'172.16.10.145', 'punch_direction': 'AUTO', 'clear_from_device_on_fetch': False, 'latitude':0.0000,'longitude':0.0000},
    
]
# Configs updating sync timestamp in the Shift Type DocType 
# please, read this thread to know why this is necessary https://discuss.erpnext.com/t/v-12-hr-auto-attendance-purpose-of-last-sync-of-checkin-in-shift-type/52997
shift_type_device_mapping = [
    {'shift_type_name': ['Shift1'], 'related_device_id': ['Machine_4']}
]

# Ignore following exceptions thrown by ERPNext and continue importing punch logs.
# Note: All other exceptions will halt the punch log import to erpnext.
#       1. No Employee found for the given employee User ID in the Biometric device.
#       2. Employee is inactive for the given employee User ID in the Biometric device.
#       3. Duplicate Employee Checkin found. (This exception can happen if you have cleared the logs/status.json of this script)
# Use the corresponding number to ignore the above exceptions. (Default: Ignores all the listed exceptions)
allowed_exceptions = [1,2,3]



# Configuration is now defined above in this file
import requests
import datetime
import json
import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
from pickledb import PickleDB
from zk import ZK, const

EMPLOYEE_NOT_FOUND_ERROR_MESSAGE = "No Employee found for the given employee field value"
EMPLOYEE_INACTIVE_ERROR_MESSAGE = "Transactions cannot be created for an Inactive Employee"
DUPLICATE_EMPLOYEE_CHECKIN_ERROR_MESSAGE = "This employee already has a log with the same timestamp"
allowlisted_errors = [EMPLOYEE_NOT_FOUND_ERROR_MESSAGE, EMPLOYEE_INACTIVE_ERROR_MESSAGE, DUPLICATE_EMPLOYEE_CHECKIN_ERROR_MESSAGE]

if 'allowed_exceptions' in globals():
    allowlisted_errors_temp = []
    for error_number in allowed_exceptions:
        allowlisted_errors_temp.append(allowlisted_errors[error_number-1])
    allowlisted_errors = allowlisted_errors_temp

device_punch_values_IN = globals().get('device_punch_values_IN', [0,4])
device_punch_values_OUT = globals().get('device_punch_values_OUT', [1,5])

# possible area of further developemt
    # Real-time events - setup getting events pushed from the machine rather then polling.
        #- this is documented as 'Real-time events' in the ZKProtocol manual.

# Notes:
# Status Keys in status.json
#  - lift_off_timestamp
#  - mission_accomplished_timestamp
#  - <device_id>_pull_timestamp
#  - <device_id>_push_timestamp
#  - <shift_type>_sync_timestamp

def main():
    """Takes care of checking if it is time to pull data based on config,
    then calling the relevant functions to pull data and push to ERPNext.

    """
    try:
        # Check if API credentials are configured
        if not ERPNEXT_API_KEY or not ERPNEXT_API_SECRET:
            error_logger.error("ERPNext API credentials not configured. Please set ERPNEXT_API_KEY and ERPNEXT_API_SECRET.")
            raise Exception("Missing ERPNext API credentials")
        
        last_lift_off_timestamp = _safe_convert_date(status.get('lift_off_timestamp'), "%Y-%m-%d %H:%M:%S.%f")
        current_time = datetime.datetime.now()
        
        if (last_lift_off_timestamp and last_lift_off_timestamp < current_time - datetime.timedelta(minutes=PULL_FREQUENCY)) or not last_lift_off_timestamp:
            status.set('lift_off_timestamp', str(datetime.datetime.now()))
            status.save()
            info_logger.info("Starting sync cycle...")
            for device in devices:
                device_attendance_logs = None
                info_logger.info("Processing Device: "+ device['device_id'])
                dump_file = get_dump_file_name_and_directory(device['device_id'], device['ip'])
                if os.path.exists(dump_file):
                    info_logger.error('Device Attendance Dump Found in Log Directory. This can mean the program crashed unexpectedly. Retrying with dumped data.')
                    with open(dump_file, 'r') as f:
                        file_contents = f.read()
                        if file_contents:
                            device_attendance_logs = list(map(lambda x: _apply_function_to_key(x, 'timestamp', datetime.datetime.fromtimestamp), json.loads(file_contents)))
                try:
                    # Sync device time if enabled
                    if SYNC_DEVICE_TIME:
                        sync_device_time(device['ip'], max_time_diff=MAX_TIME_DIFFERENCE)
                    
                    pull_process_and_push_data(device, device_attendance_logs)
                    status.set(f'{device["device_id"]}_push_timestamp', str(datetime.datetime.now()))
                    status.save()
                    if os.path.exists(dump_file):
                        os.remove(dump_file)
                    info_logger.info("Successfully processed Device: "+ device['device_id'])
                except Exception as e:
                    error_logger.exception(f'Exception when processing device {device["device_id"]}: {str(e)}')
                    # Continue processing other devices instead of stopping completely
                    continue
            if 'shift_type_device_mapping' in globals():
                update_shift_last_sync_timestamp(shift_type_device_mapping)
            status.set('mission_accomplished_timestamp', str(current_time))
            status.save()
            info_logger.info(f"Sync cycle completed successfully. Processed {len(devices)} devices.")
        else:
            # No sync needed yet
            if last_lift_off_timestamp:
                next_sync = last_lift_off_timestamp + datetime.timedelta(minutes=PULL_FREQUENCY)
                info_logger.debug(f"Next sync scheduled for: {next_sync}")
            else:
                info_logger.debug("Waiting for first sync cycle")
    except Exception as e:
        error_logger.exception(f'Exception in main function: {str(e)}')
        raise  # Re-raise to be handled by infinite_loop


def pull_process_and_push_data(device, device_attendance_logs=None):
    """ Takes a single device config as param and pulls data from that device.

    params:
    device: a single device config object from the local_config file
    device_attendance_logs: fetching from device is skipped if this param is passed. used to restart failed fetches from previous runs.
    """
    attendance_success_log_file = '_'.join(["attendance_success_log", device['device_id']])
    attendance_failed_log_file = '_'.join(["attendance_failed_log", device['device_id']])
    attendance_success_logger = setup_logger(attendance_success_log_file, '/'.join([LOGS_DIRECTORY, attendance_success_log_file])+'.log')
    attendance_failed_logger = setup_logger(attendance_failed_log_file, '/'.join([LOGS_DIRECTORY, attendance_failed_log_file])+'.log')
    if not device_attendance_logs:
        device_attendance_logs = get_all_attendance_from_device(device['ip'], device_id=device['device_id'], clear_from_device_on_fetch=device['clear_from_device_on_fetch'])
        if not device_attendance_logs:
            return
    # for finding the last successfull push and restart from that point (or) from a set 'config.IMPORT_START_DATE' (whichever is later)
    index_of_last = -1
    last_line = get_last_line_from_file('/'.join([LOGS_DIRECTORY, attendance_success_log_file])+'.log')
    import_start_date = _safe_convert_date(IMPORT_START_DATE, "%Y%m%d")
    if last_line or import_start_date:
        last_user_id = None
        last_timestamp = None
        if last_line:
            last_user_id, last_timestamp = last_line.split("\t")[4:6]
            last_timestamp = datetime.datetime.fromtimestamp(float(last_timestamp))
        if import_start_date:
            if last_timestamp:
                if last_timestamp < import_start_date:
                    last_timestamp = import_start_date
                    last_user_id = None
            else:
                last_timestamp = import_start_date
        for i, x in enumerate(device_attendance_logs):
            if last_user_id and last_timestamp:
                if last_user_id == str(x['user_id']) and last_timestamp == x['timestamp']:
                    index_of_last = i
                    break
            elif last_timestamp:
                if x['timestamp'] >= last_timestamp:
                    index_of_last = i
                    break

    for device_attendance_log in device_attendance_logs[index_of_last+1:]:
        punch_direction = device['punch_direction']
        if punch_direction == 'AUTO':
            if device_attendance_log['punch'] in device_punch_values_OUT:
                punch_direction = 'OUT'
            elif device_attendance_log['punch'] in device_punch_values_IN:
                punch_direction = 'IN'
            else:
                punch_direction = None
        erpnext_status_code, erpnext_message = send_to_erpnext(device_attendance_log['user_id'], device_attendance_log['timestamp'], device['device_id'], punch_direction, latitude=device['latitude'], longitude=device['longitude'])
        if erpnext_status_code == 200:
            attendance_success_logger.info("\t".join([erpnext_message, str(device_attendance_log['uid']),
                str(device_attendance_log['user_id']), str(device_attendance_log['timestamp'].timestamp()),
                str(device_attendance_log['punch']), str(device_attendance_log['status']),
                json.dumps(device_attendance_log, default=str)]))
        else:
            attendance_failed_logger.error("\t".join([str(erpnext_status_code), str(device_attendance_log['uid']),
                str(device_attendance_log['user_id']), str(device_attendance_log['timestamp'].timestamp()),
                str(device_attendance_log['punch']), str(device_attendance_log['status']),
                json.dumps(device_attendance_log, default=str)]))
            if not(any(error in erpnext_message for error in allowlisted_errors)):
                raise Exception('API Call to ERPNext Failed.')


def get_device_time(ip, port=4370, timeout=30):
    """Get the current time from the biometric device"""
    zk = ZK(ip, port=port, timeout=timeout)
    conn = None
    device_time = None
    try:
        conn = zk.connect()
        device_time = conn.get_time()
        info_logger.info(f"Device {ip} time: {device_time}")
        return device_time
    except Exception as e:
        error_logger.error(f"Failed to get time from device {ip}: {str(e)}")
        return None
    finally:
        if conn:
            conn.disconnect()

def sync_device_time(ip, port=4370, timeout=30, max_time_diff=300):
    """Sync device time with server time if difference is too large"""
    zk = ZK(ip, port=port, timeout=timeout)
    conn = None
    try:
        conn = zk.connect()
        device_time = conn.get_time()
        server_time = datetime.datetime.now()
        
        if device_time:
            time_diff = abs((server_time - device_time).total_seconds())
            
            if time_diff > max_time_diff:  # If difference is more than 5 minutes
                info_logger.warning(f"Device {ip} time difference is {time_diff:.2f} seconds. Syncing with server time.")
                result = conn.set_time(server_time)
                if result:
                    info_logger.info(f"Successfully synced time for device {ip}")
                    return True
                else:
                    error_logger.error(f"Failed to sync time for device {ip}")
                    return False
            else:
                info_logger.info(f"Device {ip} time is synchronized (difference: {time_diff:.2f} seconds)")
                return True
        return False
    except Exception as e:
        error_logger.error(f"Failed to sync time for device {ip}: {str(e)}")
        return False
    finally:
        if conn:
            conn.disconnect()

def get_all_attendance_from_device(ip, port=4370, timeout=30, device_id=None, clear_from_device_on_fetch=False):
    #  Sample Attendance Logs [{'punch': 255, 'user_id': '22', 'uid': 12349, 'status': 1, 'timestamp': datetime.datetime(2019, 2, 26, 20, 31, 29)},{'punch': 255, 'user_id': '7', 'uid': 7, 'status': 1, 'timestamp': datetime.datetime(2019, 2, 26, 20, 31, 36)}]
    zk = ZK(ip, port=port, timeout=timeout)
    conn = None
    attendances = []
    try:
        conn = zk.connect()
        
        # Get device time for logging and sync purposes
        device_time = conn.get_time()
        server_time = datetime.datetime.now()
        time_diff = (server_time - device_time).total_seconds() if device_time else 0
        
        info_logger.info(f"Device {ip} - Device Time: {device_time}, Server Time: {server_time}, Difference: {time_diff:.2f} seconds")
        
        # Store device time information
        status.set(f'{device_id}_device_time', str(device_time) if device_time else None)
        status.set(f'{device_id}_time_difference', time_diff)
        
        x = conn.disable_device()
        # device is disabled when fetching data
        info_logger.info("\t".join((ip, "Device Disable Attempted. Result:", str(x))))
        attendances = conn.get_attendance()
        info_logger.info("\t".join((ip, "Attendances Fetched:", str(len(attendances)))))
        status.set(f'{device_id}_push_timestamp', None)
        status.set(f'{device_id}_pull_timestamp', str(server_time))
        status.save()
        if len(attendances):
            # keeping a backup before clearing data incase the programs fails.
            # if everything goes well then this file is removed automatically at the end.
            dump_file_name = get_dump_file_name_and_directory(device_id, ip)
            with open(dump_file_name, 'w+') as f:
                f.write(json.dumps(list(map(lambda x: x.__dict__, attendances)), default=datetime.datetime.timestamp))
            if clear_from_device_on_fetch:
                x = conn.clear_attendance()
                info_logger.info("\t".join((ip, "Attendance Clear Attempted. Result:", str(x))))
        x = conn.enable_device()
        info_logger.info("\t".join((ip, "Device Enable Attempted. Result:", str(x))))
    except:
        error_logger.exception(str(ip)+' exception when fetching from device...')
        raise Exception('Device fetch failed.')
    finally:
        if conn:
            conn.disconnect()
    return list(map(lambda x: x.__dict__, attendances))


def send_to_erpnext(employee_field_value, timestamp, device_id=None, log_type=None, latitude=None, longitude=None):
    """
    Examples: 
    
    For ERPNext, Frappe HR <= v14
    send_to_erpnext('12349',datetime.datetime.now(),'HO1','IN')

    For ERPNext, Frappe HR v15 onwards
    If 'Allow Geolocation Tracking' is on
    send_to_erpnext('12349',datetime.datetime.now(),'HO1','IN',latitude=12.34, longitude=56.78)
    """
    endpoint_app = "hrms" if ERPNEXT_VERSION > 13 else "erpnext"
    url = f"{ERPNEXT_URL}/api/method/{endpoint_app}.hr.doctype.employee_checkin.employee_checkin.add_log_based_on_employee_field"
    headers = {
        'Authorization': "token "+ ERPNEXT_API_KEY + ":" + ERPNEXT_API_SECRET,
        'Accept': 'application/json'
    }
    data = {
        'employee_field_value' : employee_field_value,
        'timestamp' : timestamp.__str__(),
        'device_id' : device_id,
        'log_type' : log_type,
        'latitude' : latitude,
        'longitude' : longitude
    }
    response = requests.request("POST", url, headers=headers, json=data)
    if response.status_code == 200:
        return 200, json.loads(response._content)['message']['name']
    else:
        error_str = _safe_get_error_str(response)
        if EMPLOYEE_NOT_FOUND_ERROR_MESSAGE in error_str:
            error_logger.error('\t'.join(['Error during ERPNext API Call.', str(employee_field_value), str(timestamp.timestamp()), str(device_id), str(log_type), error_str]))
            # TODO: send email?
        else:
            error_logger.error('\t'.join(['Error during ERPNext API Call.', str(employee_field_value), str(timestamp.timestamp()), str(device_id), str(log_type), error_str]))
        return response.status_code, error_str

def update_shift_last_sync_timestamp(shift_type_device_mapping):
    """
    ### algo for updating the sync_current_timestamp
    - get a list of devices to check
    - check if all the devices have a non 'None' push_timestamp
        - check if the earliest of the pull timestamp is greater than sync_current_timestamp for each shift name
            - then update this min of pull timestamp to the shift

    """
    for shift_type_device_map in shift_type_device_mapping:
        all_devices_pushed = True
        pull_timestamp_array = []
        for device_id in shift_type_device_map['related_device_id']:
            if not status.get(f'{device_id}_push_timestamp'):
                all_devices_pushed = False
                break
            pull_timestamp_array.append(_safe_convert_date(status.get(f'{device_id}_pull_timestamp'), "%Y-%m-%d %H:%M:%S.%f"))
        if all_devices_pushed:
            min_pull_timestamp = min(pull_timestamp_array)
            if isinstance(shift_type_device_map['shift_type_name'], str): # for backward compatibility of config file
                shift_type_device_map['shift_type_name'] = [shift_type_device_map['shift_type_name']]
            for shift in shift_type_device_map['shift_type_name']:
                try:
                    sync_current_timestamp = _safe_convert_date(status.get(f'{shift}_sync_timestamp'), "%Y-%m-%d %H:%M:%S.%f")
                    if (sync_current_timestamp and min_pull_timestamp > sync_current_timestamp) or (min_pull_timestamp and not sync_current_timestamp):
                        response_code = send_shift_sync_to_erpnext(shift, min_pull_timestamp)
                        if response_code == 200:
                            status.set(f'{shift}_sync_timestamp', str(min_pull_timestamp))
                            status.save()
                except:
                    error_logger.exception('Exception in update_shift_last_sync_timestamp, for shift:'+shift)

def send_shift_sync_to_erpnext(shift_type_name, sync_timestamp):
    url = ERPNEXT_URL + "/api/resource/Shift Type/" + shift_type_name
    headers = {
        'Authorization': "token "+ ERPNEXT_API_KEY + ":" + ERPNEXT_API_SECRET,
        'Accept': 'application/json'
    }
    data = {
        "last_sync_of_checkin" : str(sync_timestamp)
    }
    try:
        response = requests.request("PUT", url, headers=headers, data=json.dumps(data))
        if response.status_code == 200:
            info_logger.info("\t".join(['Shift Type last_sync_of_checkin Updated', str(shift_type_name), str(sync_timestamp.timestamp())]))
        else:
            error_str = _safe_get_error_str(response)
            error_logger.error('\t'.join(['Error during ERPNext Shift Type API Call.', str(shift_type_name), str(sync_timestamp.timestamp()), error_str]))
        return response.status_code
    except:
        error_logger.exception("\t".join(['exception when updating last_sync_of_checkin in Shift Type', str(shift_type_name), str(sync_timestamp.timestamp())]))

def get_last_line_from_file(file):
    # concerns to address(may be much later):
        # how will last line lookup work with log rotation when a new file is created?
            #- will that new file be empty at any time? or will it have a partial line from the previous file?
    line = None
    if os.stat(file).st_size < 5000:
        # quick hack to handle files with one line
        with open(file, 'r') as f:
            for line in f:
                pass
    else:
        # optimized for large log files
        with open(file, 'rb') as f:
            f.seek(-2, os.SEEK_END)
            while f.read(1) != b'\n':
                f.seek(-2, os.SEEK_CUR)
            line = f.readline().decode()
    return line


def setup_logger(name, log_file, level=logging.INFO, formatter=None):

    if not formatter:
        formatter = logging.Formatter('%(asctime)s\t%(levelname)s\t%(message)s')

    handler = RotatingFileHandler(log_file, maxBytes=5000000, backupCount=5)
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.hasHandlers():
        logger.addHandler(handler)

    return logger

def get_dump_file_name_and_directory(device_id, device_ip):
    return LOGS_DIRECTORY + '/' + device_id + "_" + device_ip.replace('.', '_') + '_last_fetch_dump.json'

def _apply_function_to_key(obj, key, fn):
    obj[key] = fn(obj[key])
    return obj

def _safe_convert_date(datestring, pattern):
    try:
        return datetime.datetime.strptime(datestring, pattern)
    except:
        return None

def _safe_get_error_str(res):
    try:
        error_json = json.loads(res._content)
        if 'exc' in error_json: # this means traceback is available
            error_str = json.loads(error_json['exc'])[0]
        else:
            error_str = json.dumps(error_json)
    except:
        error_str = str(res.__dict__)
    return error_str

# setup logger and status
if not os.path.exists(LOGS_DIRECTORY):
    os.makedirs(LOGS_DIRECTORY)
error_logger = setup_logger('error_logger', '/'.join([LOGS_DIRECTORY, 'error.log']), logging.ERROR)
info_logger = setup_logger('info_logger', '/'.join([LOGS_DIRECTORY, 'logs.log']))
status = PickleDB('/'.join([LOGS_DIRECTORY, 'status.json']))

def sync_all_devices_time():
    """Sync time for all configured devices on startup"""
    if SYNC_TIME_ON_STARTUP:
        info_logger.info("Syncing time for all devices on startup...")
        for device in devices:
            try:
                sync_device_time(device['ip'], max_time_diff=MAX_TIME_DIFFERENCE)
            except Exception as e:
                error_logger.error(f"Failed to sync time for device {device['device_id']}: {str(e)}")

def infinite_loop(sleep_time=15, max_consecutive_errors=5, max_backoff=300):
    print("Service Running...")
    
    # Sync device times on startup
    sync_all_devices_time()
    
    consecutive_errors = 0
    current_backoff = sleep_time
    
    while True:
        try:
            main()
            # Reset error counters on successful execution
            consecutive_errors = 0
            current_backoff = sleep_time
            time.sleep(sleep_time)
        except KeyboardInterrupt:
            print("Service stopped by user")
            break
        except SystemExit:
            print("Service stopped by system")
            break
        except Exception as e:
            consecutive_errors += 1
            error_logger.error(f"Error in main loop (attempt {consecutive_errors}): {str(e)}")
            print(f"Error occurred: {e}")
            
            if consecutive_errors >= max_consecutive_errors:
                error_msg = f"Maximum consecutive errors ({max_consecutive_errors}) reached. Stopping service."
                error_logger.critical(error_msg)
                print(error_msg)
                break
            
            # Exponential backoff with maximum limit
            current_backoff = min(current_backoff * 2, max_backoff)
            print(f"Waiting {current_backoff} seconds before retry...")
            time.sleep(current_backoff)

if __name__ == "__main__":
    infinite_loop()
