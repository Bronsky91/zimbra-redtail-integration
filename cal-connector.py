import requests
import json
import datetime
import calendar
from peewee import *

import redtail

rt_un = raw_input('Redtail Username: ')
rt_pw = raw_input('Redtail Password: ')
zimbra_username = raw_input('Zimbra Webmail Email Address: ')
zimbra_password = raw_input('Zimbra Webmail Password: ')
email_domain = raw_input('Email Domain: ')
# add in to ask for timezone
zimbra_url = 'http://webmail.{}/home/{}'.format(email_domain, zimbra_username)
zimbra_basic_auth = '&auth=ba'

zimbra_cal = zimbra_url + '/calendar?fmt=json'


def day_convert_to_timestamp(day_string):
    """
    Converts a date string (no time included) into a UTC timestamp in milliseconds
    """
    ts = datetime.datetime(year=int(day_string[:4]), month=int(
        day_string[4:6]), day=int(day_string[6:8]))
    ts = calendar.timegm(ts.timetuple()) * 1000
    return ts


def get_cal():
    """
    Parses calendar data from user's Zimbra calendar and create a list of dictionaries using Zimbra's calItemID, name of calItem, start, and end dates
    """
    r = requests.get(zimbra_cal + zimbra_basic_auth,
                     auth=(zimbra_username, zimbra_password))
    json_output = json.loads(r.text)
    cal = json_output['appt']
    month_before = datetime.datetime.utcnow() + datetime.timedelta(days=-45)
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
                    'zimbra_id': int(cal_activity['comp'][0]['calItemId'])
                })
    return send_to_redtail


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


# UserID of Redtail user
rt_user_id = redtail.get_user(rt_un, rt_pw)
# conditional to check if user record exists in database
if Calendar.select().where(Calendar.user == rt_user_id).exists():
    print 'User has calendar items in the database'
    # if there is a user then check paired ids

    # if a Zimbra id is in a pair then UPDATE the Redtail paired activity

    # if a zimbra id is not in a pair then create a new Redtail activity

# else if there's no records for user then dump zimbra cal into Redtail and create record of id pairs
else:
    zimbra_cal = get_cal()
    for cal_item in zimbra_cal:
        Calendar.create(user=rt_user_id)
        Calendar.create(zimbra=cal_item['zimbra_id'])
        Calendar.create(redtail=redtail.put_cal_item(
            rt_un, rt_pw, cal_item, 0, rt_user_id))
