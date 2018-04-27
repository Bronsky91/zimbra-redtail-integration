import requests
import json
import datetime
import calendar
import time
import getpass
from peewee import *

import redtail

rt_un = raw_input('Redtail Username: ')
rt_pw = getpass.getpass('Redtail Password: ')
zimbra_username = raw_input('Zimbra Webmail Email Address: ')
zimbra_password = getpass.getpass('Zimbra Webmail Password: ')
email_domain = zimbra_username.split('@')[1]

zimbra_url = 'http://webmail.{}/home/{}'.format(
    email_domain, zimbra_username)
zimbra_basic_auth = '&auth=ba'
zimbra_cal = zimbra_url + '/calendar?fmt=json'

db = SqliteDatabase('calendars.db')


class Calendar(Model):
    user = IntegerField(default=0)
    redtail = IntegerField(default=0)
    zimbra = IntegerField(default=0)

    class Meta:
        database = db


if __name__ == '__main__':
    db.connect()
    db.create_tables([Calendar], safe=True)
    db.close()


def day_convert_to_timestamp(date_string):
    """
    Converts a date string (no time included) into a UTC timestamp in milliseconds
    """
    ts = datetime.datetime(year=int(date_string[:4]), month=int(
        date_string[4:6]), day=int(date_string[6:8]))
    ts = calendar.timegm(ts.timetuple()) * 1000
    return ts


def get_cal():
    """
    Parses calendar data from user's Zimbra calendar and create a list of dictionaries using Zimbra's calItemID, name of calItem, start, and end dates
    """
    print ' '
    print 'Gathering Zimbra Calendar...'
    r = requests.get(zimbra_cal + zimbra_basic_auth,
                     auth=(zimbra_username, zimbra_password))
    json_output = json.loads(r.text)
    cal = json_output['appt']
    month_before = datetime.datetime.utcnow() + datetime.timedelta(days=-30)
    month_before_ts = calendar.timegm(month_before.timetuple()) * 1000
    six_months_out = datetime.datetime.utcnow() + datetime.timedelta(days=185)
    six_months_out_ts = calendar.timegm(six_months_out.timetuple()) * 1000

    send_to_redtail = []

    # Parsing zimbra cal data for 1 month ago and 6 months out.
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
            if start_time > month_before_ts and start_time < six_months_out_ts:
                send_to_redtail.append({
                    'subject': str(cal_activity['comp'][0]['name']),
                    'start_time': start_time,
                    'end_time': end_time,
                    'allday': allday,
                    'zimbra_id': int(cal_activity['comp'][0]['calItemId']),
                })
    print ' '
    print 'Zimbra Calendar Parsed - Sending to Redtail'
    print ' '
    return send_to_redtail


def check_if_cal_item_is_deleted(database_id, zimbra_cal):
    """
    Checks if a calendar item was deleted in Zimbra or is older than 30 days, if True is returned sync() will mark it complete in Redtail and remove it from the databae.
    """
    zimbra_id_list = []
    for item in zimbra_cal:
        zimbra_id_list.append(item['zimbra_id'])
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
    zimbra_cal = get_cal()

    # Current cal items in database
    db_query = Calendar.select().dicts()
    db_list = {'calendar_data': list(db_query)}

    # Loop to complete and remove deleted zimbra calendar items
    for record in db_list['calendar_data']:
        if check_if_cal_item_is_deleted(record['zimbra'], zimbra_cal):
            redtail.mark_activity_complete(rt_un, rt_pw, record['redtail'])
            Calendar.select().where(Calendar.redtail ==
                                    record['redtail']).get().delete()

    # Loop to create & update Redtail activities
    for cal_item in zimbra_cal:
        if Calendar.select().where(Calendar.zimbra == cal_item['zimbra_id']):
            redtail_recid = Calendar.select().where(
                Calendar.zimbra == cal_item['zimbra_id']).get().redtail
            # Update Redtail activity
            redtail.put_cal_item(
                rt_un, rt_pw, cal_item, redtail_recid, rt_user_id)
        else:
            # if a zimbra id is not in database then create a new Redtail activity
            Calendar.create(user=rt_user_id, zimbra=cal_item['zimbra_id'], redtail=redtail.put_cal_item(
                rt_un, rt_pw, cal_item, 0, rt_user_id))


# Timer that runs sync() every hour
while True:
    sync()
    print ' '
    print 'Sync Complete'
    print ' '
    time.sleep(3600)