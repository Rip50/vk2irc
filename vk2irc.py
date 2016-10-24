#! /usr/bin/env python
# -*- coding: utf-8 -*-

import irc.bot
import json
import textwrap
import threading
import urllib
import urllib2
import time
import sys
import os
import logging
import HTMLParser
from Queue import Queue
from urllib2 import HTTPError, URLError

irc_bot = None 
vk_bot = None
vk_api = "5.24"
irc_echo_sym = '&'
titleaudio = u'Пользователь отправил аудиозапись'
titlevideo = u'Пользователь отправил видеозапись'
titlephoto = u'Пользователь отправил фотографию'
titleurl = u'Посмотреть по ссылке'
reposturl = u'Пользователь отправил репост. Посмотреть по ссылке'
#titleaudio = titleaudio.encode(unicode(str(titleaudio), 'cp1251'), 'utf8')

class IrcBot(irc.bot.SingleServerIRCBot):
    def __init__(self, channel, nickname, server, port=6667, server_pass = '', deliver_to_irc=True):
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port, server_pass)], nickname, nickname)
        self.channel = channel
        self.deliver_to_irc = deliver_to_irc
        self.last_message_from = ""
        self.messages = Queue()
        self.update_thread = threading.Thread(target = self.update)
        self.update_thread.daemon = True
        self.update_thread.start()
        
        logging.info("Initializing irc_bot, parameters: channel = %s, nickname = %s, server = %s, port = %s, deliver_to_irc = %s" % 
                     (channel, nickname, server, str(port), deliver_to_irc))
                
    def update(self) :
        while(True) :
            time.sleep(2)
            if(self.messages.empty()) :
                continue
            message = ""
            while(not self.messages.empty()) :
                message+=self.messages.get()+"\r\n"
            invoke_res = "";
            invoke_res = vk_bot.invoke_vk('messages.send', {
                'chat_id' : vk_bot.chat_id,
                'message' : message})
            
    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        c.join(self.channel)

    def on_pubmsg(self, c, e):
        if self.deliver_to_irc == True and e.arguments[0][0] != irc_echo_sym:
            if vk_bot.is_last_message_vk == True or self.last_message_from != e.source.nick:
                message = ("%s: %s" % (e.source.nick, e.arguments[0])).encode('utf-8')
                vk_bot.is_last_message_vk = False
                self.last_message_from = e.source.nick
            else:
                message = e.arguments[0].encode('utf-8')

            self.messages.put(message)

    def send(self, msg):
        self.connection.privmsg(self.channel, msg)

class VkBot(threading.Thread):
    def __init__(self, access_token, chat_id, deliver_to_vk=True):
        super(VkBot, self).__init__()
        self.access_token = access_token
        self.chat_id = chat_id
        self.deliver_to_vk = deliver_to_vk
        self.is_last_message_vk = True
        self.last_message_from = ""
        logging.info("Initializing vk_bot, parameters: access_token = *****, chat_id = %s, deliver_to_vk = %s" % (chat_id, deliver_to_vk))

    def invoke_vk(self, method, params=dict()):
        url = 'https://api.vk.com/method/%s' % method
        constparams = {'v' : vk_api,
                       'access_token' : self.access_token}
        invoke_succeeded = False
        attempt = 0
        while attempt < 30 :
            data = urllib.urlencode(dict(constparams.items() + params.items()))
            request = urllib2.Request(url, data)
            response = urllib2.urlopen(request)
            resJson = json.loads(response.read())

            if resJson.get('error') is None:
                return resJson
            
            logging.error("Response to VK returned error: %s", resJson['error']['error_msg'])
            time_to_wait = 1
            logging.info("result=%s, waiting %s seconds", resJson, time_to_wait);
            time.sleep(time_to_wait)
            attempt += 1
        return ""
            

    def clear_url(self, url):
        result = url
        if '?' in result:
            result = result.split('?')[0]
        return result    
        
    def get_message_details(self, msg_id):
        response = self.invoke_vk('messages.getById', {'message_ids' : msg_id })
        if response['response']['count'] == 0:
            return None
        attachments = list()
        if 'attachments' in response['response']['items'][0]:
            for attach in response['response']['items'][0]['attachments']:
                if attach['type'] == 'photo':
                    for size in (2560, 1280, 807, 604, 130, 75):
                        if "photo_%s" % size in attach['photo']:
                            attachments.append({titlephoto : attach['photo']["photo_%s" % size]})
                            break
                if attach['type'] == 'audio':
                    attachments.append({titleaudio : "%s - %s" % (attach['audio']['artist'], attach['audio']['title'])
                                  } )

                if attach['type'] == 'wall':
                    attachments.append({reposturl : "https://vk.com/wall%s_%s" % (attach['wall']['to_id'], attach['wall']['id'])})
                if attach['type'] == 'video':
                    video_id = "%s_%s" % (attach['video']['owner_id'], attach['video']['id'])
                    video_details = self.invoke_vk('video.get', {'videos' : video_id})
                    if video_details['response']['count'] > 0:
                        attachments.append({titlevideo : video_details['response']['items'][0]['title']})
                        attachments.append({titleurl : video_details['response']['items'][0]['player']})
        return {'user_id' : response['response']['items'][0]['user_id'],
                'attachments' : attachments}
                
    def get_user_names(self, user_ids):
        response = self.invoke_vk('users.get', {'user_ids' : ','.join(str(x) for x in user_ids), 'name_case' : 'Nom'}) #
        result = dict()
        for user in response['response']:
            result[user['id']] = "%s %s" % (user['first_name'], user['last_name'])
        return result if len(result.items()) > 0 else None

    def load_users(self):
        response = self.invoke_vk('messages.getChat' , {'chat_id' : self.chat_id})
        return self.get_user_names(response['response']['users']) if 'users' in response['response'] else None

    def is_app_user(self, user_id):
        if self.app_user_id is None:
            response = self.invoke_vk('users.isAppUser' , {'user_id' : user_id})
            if int(response['response']) == 1:
                self.app_user_id = user_id
        return user_id == self.app_user_id

    def process_updates(self, updates):
        if len(updates) == 0:
            return
        for update in updates:
            if update[0] == 4 and (int(update[2]) & 0b10 == False):
                details = self.get_message_details(update[1])
                if details is None:
                    logging.info("VkBot process_updates: empty message details")
                    return
                user_id = details['user_id']
                if self.is_app_user(user_id):
                    return
                if user_id in self.users:
                    user_name = self.users[user_id]
                    #remove/replace special symbols
                    msg = HTMLParser.HTMLParser().unescape(update[6])
                    msg = msg.replace("<br>", "<br />")
                    name_sent = self.is_last_message_vk == True and self.last_message_from == user_name
                    self.is_last_message_vk = True
                    self.last_message_from = user_name
                    for paragraph in msg.split("<br />"):
                        for line in textwrap.wrap(paragraph, 200):
                            if name_sent == False: line = "%s: %s" % (user_name, line) 
                            name_sent = True
                            irc_bot.send(line)
                    if 'attachments' in details:
                        for attach in details['attachments']:
                            for key, value in attach.items():
                                line = "[%s] %s" % (key, value) if name_sent else "%s: [%s] %s" % (user_name, key, value)
                                name_sent = True
                                irc_bot.send(line)
                else :
                    logging.info("VkBot process_updates: user %s not in user list"%user_id)


    def get_long_poll_server(self, ts):
        response = self.invoke_vk('messages.getLongPollServer')
        return ("http://%s?act=a_check&key=%s&wait=25&mode=0&ts=%s" % 
                (response['response']['server'],
                 response['response']['key'],
                 response['response']['ts'] if ts == 0 else ts))

    def run(self):
        long_poll_server = None
        self.users = None
        self.app_user_id = None
        while True:
            if self.users is None:
                try:
                    self.users = self.load_users()
                except (HTTPError, URLError):
                    pass
                continue
            
            if long_poll_server is None:
                try:
                    long_poll_server = self.get_long_poll_server(0)
                except (HTTPError, URLError):
                    pass
                continue
            
            try:
                request = urllib2.Request(long_poll_server)
                jsonResponse = urllib2.urlopen(request)
                response = json.loads(jsonResponse.read())
            except (HTTPError, URLError):
                logging.error("Exception while sending request to server")
                long_poll_server = None
                self.users = None
                continue
            
            if 'failed' in response:
                logging.error("Server response returned \'failed\'")
                long_poll_server = None
                continue

            if 'ts' in response:
                ts = response['ts']
                try:
                    if self.deliver_to_vk == True:
                        self.process_updates(response['updates'])
                except (HTTPError, URLError):
                    logging.error("Exception while processing updates")
                    long_poll_server = None
                    self.users = None
                    continue
                try:
                    long_poll_server = self.get_long_poll_server(ts)
                except (HTTPError, URLError):
                    logging.error("Exception while getting long poll server")
                    long_poll_server = None
                    self.users = None
                    continue

def main():
    global irc_bot, vk_bot, vk_api, irc_echo_sym
    
# данный фал всегда держать в кодировке 1251 (asci - кириллица)
# секция IrcBot : название канала ; имя бота в ирк; название серванта; порт; пассворд сервера (пусто); включить* передачу сообщений из ИРК в ВК (0 либо 1)
# секция VkBot : токен ; chat_id* ; включить* передачу из ВК в ИРК (0 либо 1);
# * - все числа без кавычек.

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    irc_bot = IrcBot("Channel_Name",
                    "Bot_Name",
                    "Server_Name",
                    6667,
                    "Password",
                    True)
    vk_bot = VkBot("Token",
                   1,
                   True)
    vk_bot.daemon = True
    vk_bot.start()
    irc_bot.start()

if __name__ == "__main__":
    main()
