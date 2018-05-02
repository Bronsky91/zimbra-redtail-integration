import requests
import json
import datetime
import pytz
import calendar
import time
import getpass
import os
import glob
import re
import inquirer
from peewee import *
from icalendar import Event, Calendar

import redtail  # Custom Redtail file created to hold all Redtail API calls and API Key

timezones_question = [
    inquirer.List('tz',
                  message='Choose your Timezone',
                  choices=['US/Pacific', 'US/Arizona',
                           'US/Mountain', 'US/Central', 'US/Eastern'],
                  ),
]

# Input setup
rt_un = raw_input('Redtail Username: ')
rt_pw = getpass.getpass('Redtail Password: ')
zimbra_username = raw_input('Zimbra Webmail Email Address: ')
zimbra_password = getpass.getpass('Zimbra Webmail Password: ')
tz = inquirer.prompt(timezones_question)['tz']
timezone_offset = datetime.datetime.now(pytz.timezone(tz)).strftime('%z')
user_timezone = pytz.timezone(tz)
email_domain = zimbra_username.split('@')[1]
# Zimbra urls for API calls
zimbra_url = 'http://webmail.{}/home/{}'.format(
    email_domain, zimbra_username)
zimbra_basic_auth = '&auth=ba'
zimbra_cal = zimbra_url + '/calendar?fmt=json'
# Sqlite database setup
db = SqliteDatabase('calendars.db')
# Directory for ICS files when saved
directory = 'ics/ics_files_{}'.format(redtail.get_user(rt_un, rt_pw))
if not os.path.exists(directory):
    os.makedirs(directory)

# DB Table for Calendar Items that are sent to Redtail
class To_Redtail(Model):
    user = IntegerField(default=0)
    redtail_act_id = CharField()
    zimbra_item_id = CharField()

    class Meta:
        database = db

# DB Table for Calendar Items that are sent to Zimbra
class To_Zimbra(Model):
    user = IntegerField(default=0)
    redtail_act_id = CharField()
    zimbra_item_id = CharField()

    class Meta:
        database = db


if __name__ == '__main__':
    db.connect()
    db.create_tables([To_Redtail, To_Zimbra], safe=True)
    db.close()


def get_timestamp():
    """
    Returns a current UTC Timestamp in Milliseconds
    """
    ts = datetime.datetime.utcnow()
    return int(calendar.timegm(ts.utctimetuple()) * 1000)


last_sync = 0


def day_convert_to_timestamp(date_string):
    """
    Converts a date string (no time included) into a UTC timestamp in milliseconds
    """
    ts = datetime.datetime(year=int(date_string[:4]), month=int(
        date_string[4:6]), day=int(date_string[6:8]))
    ts = calendar.timegm(ts.timetuple()) * 1000
    return ts


def get_zimbra_cal():
    """
    Parses calendar data from user's Zimbra calendar and creates a list of dictionaries using Zimbra's 
    calItemID, name of calItem, start, and end dates
    """
    print ' '
    print 'Gathering Zimbra Calendar...'
    # Returns the user's entire Zimbra calendar 
    # --Zimbra does not return any cal items in a specific date range when requesting JSON Format-- #
    r = requests.get(zimbra_cal + zimbra_basic_auth,
                     auth=(zimbra_username, zimbra_password))
    json_output = json.loads(r.text)
    cal = json_output['appt']

    send_to_redtail = []

    # Parsing zimbra cal data for 1 month ago and 12 months out.
    for cal_item in cal:
        for cal_activity in cal_item['inv']:
            allday = False
            try:
                cal_activity['comp'][0]['allDay']
                allday = True
                start_time = cal_activity['comp'][0]['s'][0]['d']
                start_time = day_convert_to_timestamp(start_time)
                end_time = day_convert_to_timestamp(
                    cal_activity['comp'][0]['e'][0]['d'])
            except KeyError:
                start_time = cal_activity['comp'][0]['s'][0]['u']
                end_time = cal_activity['comp'][0]['e'][0]['u']
            if start_time > redtail.time_spans()['past'] and start_time < redtail.time_spans()['future']:
                send_to_redtail.append({
                    'summary': str(cal_activity['comp'][0]['name']),
                    'dtstart': start_time,
                    'dtend': end_time,
                    'allday': allday,
                    'uid': cal_activity['comp'][0]['uid'],
                    'last_update': cal_activity['comp'][0]['d']
                })
    print ' '
    print 'Zimbra Calendar Parsed'
    print ' '
    return send_to_redtail


def get_redtail_cal():
    # Redtail Calendar activites 
    rt_cal = redtail.get_cal(rt_un, rt_pw)
    sending_to_zimbra = []
    for act in rt_cal['Activities']:
        sending_to_zimbra.append({
            'summary': act['Subject'],
            'dtstart': redtail.parse_date(act['StartDate'], act['AllDayEvent'], user_timezone),
            'dtend': redtail.parse_date(act['EndDate'], act['AllDayEvent'], user_timezone),
            'desc': act['Note'],
            'uid': '{}_{}'.format(act['RecID'],re.search(r'\d+', act['StartDate']).group()),
            'allday': act['AllDayEvent'],
            'last_update': int(re.search(r'\d+', act['LastUpdate']).group())
        })
    return sending_to_zimbra


def send_to_zimbra(act):
    # Create .ics file and place them into calendar
    c = Calendar()
    e = Event()
    e.add('uid', act['uid'])
    e.add('summary', act['summary'])
    e.add('dtstart', act['dtstart'])
    e.add('dtend', act['dtend'])
    e.add('DESCRIPTION', act['desc'])
    e.add('X-MICROSOFT-CDO-ALLDAYEVENT', act['allday'])
    c.add_component(e)
    with open('{}/to_zimbra_{}.ics'.format(directory, act['uid']), 'w+') as f:
        f.write(c.to_ical())
    # Sends ICS file to Zimbra to import the appointment
    with open('{}/to_zimbra_{}.ics'.format(directory, act['uid']), 'rb') as f:
        r = requests.post(zimbra_url + '/calendar?fmt=ics',
                          auth=(zimbra_username, zimbra_password),
                          files={'{}/to_zimbra_{}.ics'.format(directory, act['uid']): f})
        if r.status_code == requests.codes.ok:
            print 'Sent "{} {}" ics file to Zimbra'.format(
                act['summary'], act['dtstart'])


def check_if_cal_item_is_deleted(database_id, zimbra_cal):
    """
    Checks if a calendar item was deleted in Zimbra or is older than 30 days, if True is returned sync() will mark it complete in Redtail and remove it from the databae.
    """
    zimbra_id_list = []
    for item in zimbra_cal:
        zimbra_id_list.append(item['uid'])
    if database_id in zimbra_id_list:
        return False
    else:
        return True


def sync():
    """
    Creates/Updates the calendar items from Zimbra into the Redtail calendar
    """
    # UserID of Redtail user
    rt_user_id = redtail.get_user(rt_un, rt_pw)
    # Parsed Zimbra calendar data
    zimbra_cal = get_zimbra_cal()
    redtail_cal = get_redtail_cal()
    # Current cal items in database
    db_query = To_Redtail.select().dicts()
    db_list = {'to_redtail_data': list(db_query)}

    # Loop to create & update Zimbra activities
    for event in redtail_cal:
        if To_Redtail.select().where(To_Redtail.redtail_act_id == event['uid']):
            if event['last_update'] > last_sync:
                zimbra_uid = To_Redtail.select().where(
                    To_Redtail.redtail_act_id == event['uid']).get().zimbra_item_id
                rt_id = event['uid']
                event['uid'] = zimbra_uid
                send_to_zimbra(event)
                To_Zimbra.create(
                    user=rt_user_id, zimbra_item_id=event['uid'], redtail_act_id=rt_id)
        elif To_Zimbra.select().where(To_Zimbra.zimbra_item_id == event['uid']):
            if event['last_update'] > last_sync:
                zimbra_uid = To_Zimbra.select().where(
                    To_Zimbra.zimbra_item_id == event['uid']).get().zimbra_item_id
                event['uid'] = zimbra_uid
                send_to_zimbra(event)
        else:
            send_to_zimbra(event)
            To_Zimbra.create(
                user=rt_user_id, zimbra_item_id=event['uid'], redtail_act_id=event['uid'])

    # Loop to create & update Redtail activities
    for cal_item in zimbra_cal:
        if To_Redtail.select().where(To_Redtail.zimbra_item_id == cal_item['uid']):
            if cal_item['last_update'] > last_sync:
                db_record = To_Redtail.select().where(
                    To_Redtail.zimbra_item_id == cal_item['uid'])
                redtail_recid = db_record.get().redtail_act_id
                # Update Redtail activity
                redtail.put_cal_item(
                    rt_un, rt_pw, cal_item, redtail_recid, rt_user_id, timezone_offset)
        elif To_Zimbra.select().where(To_Zimbra.redtail_act_id == cal_item['uid']):
            if cal_item['last_update'] > last_sync:
                redtail_recid = To_Zimbra.select().where(
                    To_Zimbra.redtail_act_id == cal_item['uid']).get().redtail_act_id
                # Update Redtail activity
                redtail.put_cal_item(
                    rt_un, rt_pw, cal_item, redtail_recid, rt_user_id, timezone_offset)
        else:
            # if a zimbra id is not in database then create a new Redtail activity
            To_Redtail.create(user=rt_user_id, zimbra_item_id=cal_item['uid'], redtail_act_id=redtail.put_cal_item(
                rt_un, rt_pw, cal_item, 0, rt_user_id, timezone_offset))

    # Loop to complete and remove deleted zimbra calendar items in Redtail
    for record in db_list['to_redtail_data']:
        if check_if_cal_item_is_deleted(record['zimbra_item_id'], zimbra_cal):
            redtail.mark_activity_complete(
                rt_un, rt_pw, record['redtail_act_id'])
            To_Redtail.select().where(To_Redtail.redtail_act_id ==
                                      record['redtail_act_id']).get().delete()


# Timer that runs sync() every 30 min and sets the last_sync variable
while True:
    sync()
    last_sync = get_timestamp()
    timezone_offset = datetime.datetime.now(pytz.timezone(tz)).strftime('%z')
    print ' '
    print 'Sync Complete'
    print ' '
    time.sleep(1800)  # 30 minutes
