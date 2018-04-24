import requests, json, datetime

import redtail

rt_username = raw_input('Redtail Username: ')
rt_password = raw_input('Redtail Password: ')
zimbra_username = raw_input('Zimbra Webmail Email Address: ')
zimbra_password = raw_input('Zimbra Webmail Password: ')
email_domain = raw_input('Email Domain: ')

zimbra_url = 'http://webmail.{}/home/{}'.format(email_domain, zimbra_username)
zimbra_basic_auth = '&auth=ba'

zimbra_cal = zimbra_url + 'calendar?fmt=json'

def get_cal():
    r = requests.get(zimbra_cal + zimbra_basic_auth, auth=(zimbra_username, zimbra_password))
    # Has to return the whole calendar
    # 'appt: ['inv': [
    #                   {'type': 'appt',
    #                    'comp': [
    #                           {
    #                            'name': 'cal_item_name',
    #                            'fr': 'short description'
    #                            's': [{'d':timestamp
    #                                   'tz':timezone
    #                                  }]                              
    #                            }
    #                             ]
    #                       }
    #               ]
    #           ]