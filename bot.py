import os
import re
import sqlite3
import time
import requests
from datetime import datetime
from collections import defaultdict

# ==================== CONFIG FROM ENV ====================
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN = int(os.environ.get("ADMIN_ID", "0"))
ALLOWED = os.environ.get("ALLOWED_DOMAINS", "animethic.in,animethic.xyz").split(",")
WARN_MAX = int(os.environ.get("WARN_LIMIT", "3"))
MUTE_MINS = int(os.environ.get("MUTE_MINUTES", "10"))
FLOOD_MAX = int(os.environ.get("FLOOD_LIMIT", "5"))

print(f"Token: {'SET' if TOKEN else 'MISSING'}")
print(f"Admin: {ADMIN if ADMIN else 'MISSING'}")

if not TOKEN or not ADMIN:
    raise SystemExit("ERROR: BOT_TOKEN and ADMIN_ID must be set!")

# ==================== DATABASE ====================
conn = sqlite3.connect('data.db', check_same_thread=False)
c = conn.cursor()
c.executescript('''
    CREATE TABLE IF NOT EXISTS warns(user_id INT, chat_id INT, count INT DEFAULT 1, PRIMARY KEY(user_id, chat_id));
    CREATE TABLE IF NOT EXISTS faq(k TEXT UNIQUE, r TEXT);
    CREATE TABLE IF NOT EXISTS reports(d TEXT, w INT DEFAULT 0, m INT DEFAULT 0, s INT DEFAULT 0, j INT DEFAULT 0, PRIMARY KEY(d));
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
''')
conn.commit()

# ==================== GLOBAL ====================
flood = defaultdict(list)
join_times = defaultdict(list)
SCAM = ['free nitro','giveaway','airdrop','click here','claim','verify','earn money','free gift','crypto','double your','lottery','won prize','limited offer','act now','exclusive deal']

# ==================== HELPERS ====================
def api(m, p={}):
    try:
        r = requests.post(f'https://api.telegram.org/bot{TOKEN}/{m}', json=p, timeout=10)
        return r.json()
    except:
        return {'ok': False}

def send(chat, text):
    return api('sendMessage', {'chat_id': chat, 'text': text, 'parse_mode': 'HTML'})

def delete(chat, msg):
    try: api('deleteMessage', {'chat_id': chat, 'message_id': msg})
    except: pass

def mute_user(chat, user, mins):
    until = int(time.time()) + mins * 60
    api('restrictChatMember', {'chat_id': chat, 'user_id': user, 'permissions': {'can_send_messages': False}, 'until_date': until})

def unmute_user(chat, user):
    api('restrictChatMember', {'chat_id': chat, 'user_id': user, 'permissions': {'can_send_messages': True, 'can_send_media': True, 'can_send_other': True}})

def is_admin(chat, user):
    r = api('getChatMember', {'chat_id': chat, 'user_id': user})
    s = r.get('result', {}).get('status', '')
    return s in ['creator', 'administrator']

def is_scam(text):
    if not text: return False
    t = text.lower()
    return any(w in t for w in SCAM)

def get_links(text):
    if not text: return []
    return re.findall(r'https?://[^\s]+', text)

def is_allowed(url):
    try:
        d = url.replace('https://', '').replace('http://', '').split('/')[0].lower()
        return d in ALLOWED
    except: return False

def is_flood(user):
    now = time.time()
    flood[user].append(now)
    flood[user] = [t for t in flood[user] if now - t < 10]
    return len(flood[user]) > FLOOD_MAX

def is_raid(chat):
    now = time.time()
    join_times[chat].append(now)
    join_times[chat] = [t for t in join_times[chat] if now - t < 60]
    return len(join_times[chat]) >= 10

def get_warns(user, chat):
    r = c.execute('SELECT count FROM warns WHERE user_id=? AND chat_id=?', (user, chat)).fetchone()
    return r[0] if r else 0

def add_warn(user, chat):
    c.execute('INSERT INTO warns VALUES(?,?,1) ON CONFLICT(user_id,chat_id) DO UPDATE SET count=count+1', (user, chat))
    conn.commit()

def reset_warns(user, chat):
    c.execute('DELETE FROM warns WHERE user_id=? AND chat_id=?', (user, chat))
    conn.commit()

def add_report(field, val=1):
    c.execute(f'INSERT INTO reports(d,{field}) VALUES(date("now"),{val}) ON CONFLICT(d) DO UPDATE SET {field}={field}+{val}')
    conn.commit()

def get_setting(chat, key):
    r = c.execute('SELECT v FROM settings WHERE k=?', (f'{chat}_{key}',)).fetchone()
    return r[0] if r else 'on'

def set_setting(chat, key, val):
    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (f'{chat}_{key}', val))
    conn.commit()

# ==================== VIOLATION HANDLER ====================
def handle_violation(chat, user, name, reason):
    add_warn(user, chat)
    w = get_warns(user, chat)
    add_report('w')
    msg = f'⚠️ {name}\n{reason}!\nWarnings: {w}/{WARN_MAX}'
    if w >= WARN_MAX:
        mute_user(chat, user, MUTE_MINS)
        add_report('m')
        msg += f'\n\n🔇 Muted {MUTE_MINS} minutes!'
        send(ADMIN, f'⚠️ {name} ({user}) muted\nReason: {reason}\nChat: {chat}')
        try: send(user, f'🔇 Muted {MUTE_MINS} min. Read /rules')
        except: pass
    s = send(chat, msg)
    if s.get('ok'):
        time.sleep(8)
        delete(chat, s['result']['message_id'])

# ==================== DM HANDLER ====================
def handle_dm(m):
    uid = m['from']['id']
    if uid != ADMIN:
        send(uid, '⛔ Unauthorized')
        return
    t = m.get('text', '')
    a = t.split()
    cmd = a[0].lower()
    cid = m['chat']['id']
    if cmd in ['/start', '/admin']:
        send(cid, '🎌 <b>Mikasa Ackerman Admin Panel</b>\n\n/faq_add key|response\n/faq_del key\n/faq_list\n/report\n/rules\n/help')
    elif cmd == '/faq_add':
        x = t.replace('/faq_add ', '', 1)
        p = x.split('|')
        if len(p) < 2: send(cid, '❌ /faq_add key|response'); return
        c.execute('INSERT OR REPLACE INTO faq VALUES(?,?)', (p[0].strip().lower(), p[1].strip()))
        conn.commit()
        send(cid, f'✅ Added: {p[0].strip()}')
    elif cmd == '/faq_del':
        if len(a) < 2: send(cid, '❌ /faq_del key'); return
        c.execute('DELETE FROM faq WHERE k=?', (a[1].lower(),))
        conn.commit()
        send(cid, f'✅ Deleted: {a[1]}')
    elif cmd == '/faq_list':
        r = c.execute('SELECT * FROM faq').fetchall()
        if not r: send(cid, '📋 Empty'); return
        l = '📋 <b>FAQs</b>\n\n'
        for k, v in r: l += f'🔹 <b>{k}</b>: {v}\n\n'
        send(cid, l)
    elif cmd == '/report':
        d = a[1] if len(a) > 1 else datetime.now().strftime('%Y-%m-%d')
        r = c.execute('SELECT * FROM reports WHERE d=?', (d,)).fetchone()
        if r: send(cid, f'📊 {d}\n⚠️ Warns: {r[1]}\n🔇 Mutes: {r[2]}\n🗑️ Spam: {r[3]}\n👥 Joins: {r[4]}')
        else: send(cid, f'📊 No data for {d}')
    elif cmd == '/rules':
        send(cid, '📜 <b>RULES</b>\n\n1. Anime only\n2. No promo/scam\n3. No other channel/website\n4. Only animethic.in/.xyz\n5. No hate speech\n6. Be friendly\n\n⚠️ 3 warns = 10min mute')

# ==================== GROUP COMMAND HANDLER ====================
def handle_cmd(m):
    chat = m['chat']['id']
    user = m['from']['id']
    t = m.get('text', '')
    a = t.split()
    cmd = a[0].lower().split('@')[0]
    adm = is_admin(chat, user)
    reply = m.get('reply_to_message')
    
    if cmd == '/start': send(chat, '🎌 Mikasa Ackerman protecting!')
    elif cmd == '/help': send(chat, '/help /rules\nAdmins: /warn /resetwarn /warnings /mute /unmute /kick /ban /purge /settings /toggle')
    elif cmd == '/rules': send(chat, '📜 <b>RULES</b>\n\n1. Anime only\n2. No promo\n3. No other channel/website\n4. Only animethic.in/.xyz\n5. No hate\n6. Be friendly\n\n⚠️ 3 warns = 10min mute')
    elif cmd == '/warn' and adm and reply:
        t = reply['from']
        add_warn(t['id'], chat)
        w = get_warns(t['id'], chat)
        add_report('w')
        msg = f'⚠️ {t["first_name"]}\nWarnings: {w}/{WARN_MAX}'
        if w >= WARN_MAX:
            mute_user(chat, t['id'], MUTE_MINS)
            add_report('m')
            msg += f'\n🔇 Muted {MUTE_MINS} min!'
        send(chat, msg)
    elif cmd == '/resetwarn' and adm and reply:
        reset_warns(reply['from']['id'], chat)
        send(chat, '✅ Reset')
    elif cmd == '/warnings' and adm and reply:
        w = get_warns(reply['from']['id'], chat)
        send(chat, f'⚠️ {reply["from"]["first_name"]}: {w}/{WARN_MAX}')
    elif cmd == '/mute' and adm and reply:
        mins = int(a[1]) if len(a) > 1 else MUTE_MINS
        mute_user(chat, reply['from']['id'], mins)
        send(chat, f'🔇 Muted {mins} min')
    elif cmd == '/unmute' and adm and reply:
        unmute_user(chat, reply['from']['id'])
        send(chat, '✅ Unmuted')
    elif cmd == '/kick' and adm and reply:
        api('banChatMember', {'chat_id': chat, 'user_id': reply['from']['id']})
        api('unbanChatMember', {'chat_id': chat, 'user_id': reply['from']['id']})
        send(chat, '👢 Kicked')
    elif cmd == '/ban' and adm and reply:
        api('banChatMember', {'chat_id': chat, 'user_id': reply['from']['id']})
        send(chat, '🚫 Banned')
    elif cmd == '/purge' and adm and reply:
        n = min(int(a[1]) if len(a) > 1 else 10, 100)
        delete(chat, m['message_id'])
        for i in range(n): delete(chat, reply['message_id'] + i)
    elif cmd == '/settings' and adm:
        s1 = get_setting(chat, 'anti_spam')
        s2 = get_setting(chat, 'anti_flood')
        s3 = get_setting(chat, 'link_filter')
        s4 = get_setting(chat, 'welcome')
        send(chat, f'⚙️ Settings\n🛡️ Anti-Spam: {s1}\n🌊 Anti-Flood: {s2}\n🔗 Link Filter: {s3}\n👋 Welcome: {s4}')
    elif cmd == '/toggle' and adm and len(a) > 2:
        f, v = a[1].lower(), a[2].lower()
        if v in ['on', 'off']:
            set_setting(chat, f, v)
            send(chat, f'✅ {f} = {v}')

# ==================== MAIN ====================
def process(u):
    if 'message' in u:
        m = u['message']
        cid = m['chat']['id']
        uid = m['from']['id']
        txt = m.get('text', '')
        if cid == uid: handle_dm(m); return
        if txt.startswith('/'): handle_cmd(m); return
        if is_admin(cid, uid): return
        if get_setting(cid, 'anti_flood') != 'off' and is_flood(uid):
            delete(cid, m['message_id']); mute_user(cid, uid, 5); add_report('s'); send(cid, '🌊 Flood! Muted 5min.'); return
        if get_setting(cid, 'anti_spam') != 'off' and is_scam(txt):
            delete(cid, m['message_id']); handle_violation(cid, uid, m['from']['first_name'], 'Scam'); return
        if get_setting(cid, 'link_filter') != 'off':
            for l in get_links(txt):
                if not is_allowed(l):
                    delete(cid, m['message_id']); handle_violation(cid, uid, m['from']['first_name'], 'Unauthorized link'); return
        faq_r = c.execute('SELECT r FROM faq WHERE k=?', (txt.strip().lower(),)).fetchone()
        if faq_r: send(cid, faq_r[0])
    elif 'chat_member' in u:
        cm = u['chat_member']
        if cm.get('new_chat_member', {}).get('status') == 'member':
            cid = cm['chat']['id']; user = cm['new_chat_member']['user']
            add_report('j')
            if is_raid(cid): send(ADMIN, f'🚨 Raid! {cid}')
            if get_setting(cid, 'welcome') != 'off':
                send(cid, f'🎌 Welcome, {user["first_name"]}!\n\n📜 /rules\n🔗 Only animethic.in/.xyz')

def main():
    print("🎌 Mikasa Ackerman Bot Started!")
    offset = 0
    while True:
        try:
            r = requests.get(f'https://api.telegram.org/bot{TOKEN}/getUpdates', params={'offset': offset, 'timeout': 30}, timeout=35)
            data = r.json()
            if data.get('ok'):
                for u in data['result']:
                    offset = u['update_id'] + 1
                    process(u)
        except Exception as e:
            print(f'Error: {e}')
            time.sleep(2)

if __name__ == '__main__':
    main()
