#!/usr/bin/env python
"""win: token-lean Windows app CLI for AI agents, over UI Automation.
Docs: README.md next to this file. Needs: comtypes, pywin32, Pillow (shot only)."""
import sys, os, json, time, ctypes, re, subprocess, shlex
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixel coordinates
except Exception:
    pass

import comtypes, comtypes.client
comtypes.CoInitialize()
comtypes.client.GetModule('UIAutomationCore.dll')
from comtypes.gen import UIAutomationClient as U
import win32gui, win32con, win32process, win32api

UIA = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
STATE = os.path.join(os.path.expanduser('~'), '.win-cli', 'state.json')
user32 = ctypes.windll.user32


class Fail(Exception):
    pass


# ---------- UIA ids ----------
P = dict(rid=30000, rect=30001, pid=30002, type=30003, kbfocus=30008, enabled=30010, aid=30011, cls=30012,
         hwnd=30020, offscreen=30022, name=30005, inv=30031, val=30043, tog=30041, sel=30036, exp=30028,
         value=30045, ro=30046, toggle=30086, expstate=30070, selected=30079)
T = {50000: 'button', 50001: 'calendar', 50002: 'checkbox', 50003: 'combobox', 50004: 'edit', 50005: 'link',
     50006: 'image', 50007: 'listitem', 50008: 'list', 50009: 'menu', 50010: 'menubar', 50011: 'menuitem',
     50012: 'progress', 50013: 'radio', 50014: 'scrollbar', 50015: 'slider', 50016: 'spinner', 50017: 'statusbar',
     50018: 'tab', 50019: 'tabitem', 50020: 'text', 50021: 'toolbar', 50022: 'tooltip', 50023: 'tree',
     50024: 'treeitem', 50025: 'custom', 50026: 'group', 50027: 'thumb', 50028: 'grid', 50029: 'dataitem',
     50030: 'document', 50031: 'splitbutton', 50032: 'window', 50033: 'pane', 50034: 'header', 50035: 'headeritem',
     50036: 'table', 50037: 'titlebar', 50038: 'separator', 50039: 'zoom', 50040: 'appbar'}
INTERACTIVE = {'button', 'checkbox', 'combobox', 'edit', 'link', 'listitem', 'menuitem', 'radio', 'slider', 'spinner',
               'tabitem', 'treeitem', 'dataitem', 'document', 'splitbutton', 'headeritem'}
SKIP = {'scrollbar', 'thumb', 'separator', 'tooltip', 'titlebar'}
FOLD_MIN = 8


def clip(s, n):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1] + '…'


# ---------- state ----------
def load():
    try:
        with open(STATE, encoding='utf8') as f:
            return json.load(f)
    except Exception:
        return {'n': 0, 'refs': {}}


def save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    if len(st['refs']) > 3000:  # keep the newest refs only
        keep = sorted(st['refs'], key=lambda r: int(r[1:]))[-2000:]
        st['refs'] = {k: st['refs'][k] for k in keep}
    with open(STATE, 'w', encoding='utf8') as f:
        json.dump(st, f)


# ---------- windows ----------
def proc_name(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        buf = ctypes.create_unicode_buffer(512)
        n = wintypes.DWORD(512)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
        ctypes.windll.kernel32.CloseHandle(h)
        return os.path.basename(buf.value).lower()
    except Exception:
        return '?'


def cloaked(hwnd):
    v = ctypes.c_int(0)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), 4)
    return v.value != 0


def windows():
    out = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) and not cloaked(h) \
                and not (win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW):
            out.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    return out  # z-order, topmost first


def wid(h):
    return 'w%x' % h


def find_window(arg):
    if not arg:
        raise Fail('needs a window: id from win list, or part of its title or exe name')
    if re.fullmatch(r'w[0-9a-f]+', arg):
        h = int(arg[1:], 16)
        if not win32gui.IsWindow(h):
            raise Fail(f'window {arg} is gone, run win list')
        return h
    a = arg.lower()
    for h in windows():
        if a in win32gui.GetWindowText(h).lower() or a == proc_name(h) or a + '.exe' == proc_name(h):
            return h
    raise Fail(f'no window matches "{arg}", run win list')


def head(h):
    st = ' [min]' if win32gui.IsIconic(h) else ''
    return f'@ {wid(h)} "{clip(win32gui.GetWindowText(h), 80)}" {proc_name(h)}{st}'


# ---------- tree ----------
def cache_req():
    r = UIA.CreateCacheRequest()
    for v in P.values():
        r.AddProperty(v)
    r.TreeScope = 7  # element + subtree
    r.TreeFilter = UIA.ControlViewCondition
    return r


def snapshot(h, el=None):
    """Whole control tree of a window (or one element) in one cross-process call -> nested dicts."""
    root = (el or UIA.ElementFromHandle(h)).BuildUpdatedCache(cache_req())

    def conv(e):
        g = e.GetCachedPropertyValue
        n = {'el': e, 'type': T.get(g(P['type']), 'custom'), 'name': g(P['name']) or '', 'aid': g(P['aid']) or '',
             'cls': g(P['cls']) or '', 'rid': list(g(P['rid']) or []), 'off': bool(g(P['offscreen'])),
             'enabled': bool(g(P['enabled'])), 'inv': bool(g(P['inv'])), 'val': bool(g(P['val'])),
             'tog': bool(g(P['tog'])), 'sel': bool(g(P['sel'])), 'exp': bool(g(P['exp'])),
             'value': g(P['value']) if g(P['val']) else None, 'toggle': g(P['toggle']) if g(P['tog']) else None,
             'selected': bool(g(P['selected'])) if g(P['sel']) else None,
             'expstate': g(P['expstate']) if g(P['exp']) else None, 'rect': g(P['rect']), 'kids': []}
        try:
            arr = e.GetCachedChildren()
        except Exception:
            arr = None
        if arr:
            n['kids'] = [conv(arr.GetElement(i)) for i in range(arr.Length)]
        return n

    return conv(root)


def interactive(n):
    return n['type'] in INTERACTIVE or n['inv'] or n['tog']


class Refs:
    def __init__(self, st, h):
        self.st, self.h = st, h
        self.byrid = {tuple(v['rid']): k for k, v in st['refs'].items() if v['hwnd'] == h and v['rid']}

    def get(self, n):
        k = self.byrid.get(tuple(n['rid'])) if n['rid'] else None
        if not k:
            self.st['n'] += 1
            k = 'c%d' % self.st['n']
            if n['rid']:
                self.byrid[tuple(n['rid'])] = k
        self.st['refs'][k] = {'hwnd': self.h, 'rid': n['rid'], 'type': n['type'], 'name': n['name'], 'aid': n['aid']}
        return k


def tok(n, refs):
    s = f'[{refs.get(n)} {n["type"]} "{clip(n["name"], 60)}"'
    if n['toggle'] is not None and n['type'] in ('checkbox', 'radio', 'button', 'menuitem', 'listitem', 'treeitem'):
        s += ' [x]' if n['toggle'] == 1 else ' [-]' if n['toggle'] == 2 else ' [ ]'
    if n['selected']:
        s += ' selected'
    if n['value'] is not None and n['type'] in ('edit', 'combobox', 'document', 'spinner', 'slider') or \
            (n['value'] and n['type'] not in ('link',)):
        s += f' ="{clip(str(n["value"]), 50)}"'
    if n['expstate'] in (0, 1) and n['type'] in ('combobox', 'treeitem', 'menuitem', 'splitbutton', 'button'):
        s += ' collapsed' if n['expstate'] == 0 else ' expanded'
    if not n['enabled']:
        s += ' disabled'
    return s + ']'


def sig(n):
    return n['type'] + '.' + n['cls']


def outline(root, refs, o):
    """Render a snapshot as compact lines. Unnamed containers are transparent."""
    show_all = o.get('all')

    def visible(n):
        return n['type'] not in SKIP and (show_all or not n['off'])

    def render(n, depth, out):
        if not visible(n):
            return
        ind = '  ' * depth
        if interactive(n):
            out.append(ind + tok(n, refs))
            # menus/lists/trees: expanded children still matter (e.g. open submenu items)
            if n['kids'] and n['type'] in ('combobox', 'treeitem', 'menuitem', 'splitbutton', 'dataitem', 'listitem') and n['expstate'] == 1:
                children(n, depth + 1, out)
            elif n['kids'] and n['type'] in ('dataitem', 'listitem'):
                children(n, depth + 1, out)
            return
        if n['type'] in ('text', 'image', 'statusbar', 'progress'):
            if n['name'] or n['value']:
                extra = f' ={clip(str(n["value"]), 40)}' if n['type'] == 'progress' and n['value'] else ''
                out.append(ind + ('img "%s"' % clip(n['name'], 80) if n['type'] == 'image' else clip(n['name'], 200)) + extra)
            children(n, depth, out)
            return
        if n['name'] and n['type'] not in ('pane', 'custom') or n['type'] in ('menubar', 'toolbar', 'list', 'tree', 'tab', 'grid', 'table', 'menu', 'group') and n['name']:
            out.append(ind + f'{n["type"]} "{clip(n["name"], 50)}":')
            children(n, depth + 1, out)
        else:
            children(n, depth, out)

    def children(n, depth, out):
        kids = [k for k in n['kids'] if visible(k)]
        i = 0
        while i < len(kids):
            j = i
            while j < len(kids) and sig(kids[j]) == sig(kids[i]):
                j += 1
            run = kids[i:j]
            show = o.get('show')
            if show and len(run) >= max(FOLD_MIN, show + 3):
                for k in run[:show]:
                    render(k, depth, out)
                out.append('  ' * depth + f'…+{len(run) - show} similar (win tree {wid(refs.h)} --expand {refs.get(n)})')
            else:
                for k in run:
                    render(k, depth, out)
            i = j

    def draw(show):
        out = []
        o['show'] = show
        render(root, 0, out)
        return join(out)

    mx = float('inf') if o.get('raw') else int(o.get('max') or 8000)
    lines = draw(None)
    if not o.get('nofold') and len('\n'.join(lines)) > mx:
        for show in (40, 20, 10, 5):
            lines = draw(show)
            if len('\n'.join(lines)) <= mx:
                break
    if o.get('interactive'):
        lines = [l for l in lines if '[c' in l or l.rstrip().endswith(':') or 'similar (win' in l]
    if o.get('lines'):
        extra = len(lines) - o['lines']
        lines = lines[:o['lines']] + ([f'…+{extra} lines (win tree)'] if extra > 0 else [])
    s = '\n'.join(lines)
    if len(s) > mx:
        s = s[:int(mx)] + f'\n…truncated, {len(s) / 1000:.1f}k chars. Narrow with --region <ref> or --max N'
    return s or '(no controls)'


def join(lines):
    """Merge runs of sibling tokens at the same indent into one line (<=160 chars)."""
    out = []
    for l in lines:
        st = l.lstrip()
        if out and st.startswith('[c') and out[-1].lstrip().startswith('[c') and \
                len(l) - len(st) == len(out[-1]) - len(out[-1].lstrip()) and len(out[-1]) + len(st) < 160 \
                and ' similar ' not in out[-1]:
            out[-1] += ' ' + st
        else:
            out.append(l)
    return out


def walk(n):
    yield n
    for k in n['kids']:
        yield from walk(k)


def find_node(root, rid):
    for n in walk(root):
        if n['rid'] == rid:
            return n


# ---------- resolve a ref back to a live element ----------
def resolve(st, ref):
    if not re.fullmatch(r'c\d+', ref or ''):
        raise Fail('needs a ref like c12 (from win tree or win find)')
    r = st['refs'].get(ref)
    if not r:
        raise Fail(f'unknown ref {ref}, run win tree or win find again')
    h = r['hwnd']
    if not win32gui.IsWindow(h):
        raise Fail(f'window for {ref} is gone, run win list')
    root = snapshot(h)
    n = find_node(root, r['rid'])
    if not n:  # element re-created: same type+name+aid is good enough
        n = next((x for x in walk(root) if x['type'] == r['type'] and x['name'] == r['name'] and x['aid'] == r['aid']), None)
    if not n:
        raise Fail(f'stale ref {ref}, run win tree or win find again')
    return h, n, root


def pattern(n, pid, iface):
    return n['el'].GetCurrentPattern(pid).QueryInterface(iface)


# ---------- real input (only with --real; takes focus) ----------
def front(h):
    if win32gui.IsIconic(h):
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
    try:
        win32api.keybd_event(0x12, 0, 0, 0)  # alt tap lifts the foreground lock
        win32gui.SetForegroundWindow(h)
        win32api.keybd_event(0x12, 0, 2, 0)
    except Exception:
        pass
    time.sleep(0.15)


def real_click(h, n, double=False):
    front(h)
    l, t, w, hh = n['el'].CurrentBoundingRectangle.left, n['el'].CurrentBoundingRectangle.top, \
        n['el'].CurrentBoundingRectangle.right - n['el'].CurrentBoundingRectangle.left, \
        n['el'].CurrentBoundingRectangle.bottom - n['el'].CurrentBoundingRectangle.top
    x, y = int(l + w / 2), int(t + hh / 2)
    old = win32api.GetCursorPos()
    win32api.SetCursorPos((x, y))
    for _ in range(2 if double else 1):
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    time.sleep(0.05)
    win32api.SetCursorPos(old)


VK = {'enter': 0x0D, 'tab': 0x09, 'escape': 0x1B, 'esc': 0x1B, 'backspace': 0x08, 'delete': 0x2E, 'space': 0x20,
      'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27, 'home': 0x24, 'end': 0x23, 'pageup': 0x21,
      'pagedown': 0x22, 'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75, 'f7': 0x76,
      'f8': 0x77, 'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B, 'win': 0x5B,
      'arrowup': 0x26, 'arrowdown': 0x28, 'arrowleft': 0x25, 'arrowright': 0x27}
MOD = {'ctrl': 0x11, 'control': 0x11, 'shift': 0x10, 'alt': 0x12, 'win': 0x5B}


def parse_combo(combo):
    parts = combo.split('+')
    key = parts[-1].lower()
    mods = []
    for m in parts[:-1]:
        if m.lower() not in MOD:
            raise Fail(f'unknown modifier {m}')
        mods.append(MOD[m.lower()])
    if key in VK:
        vk = VK[key]
    elif len(key) == 1:
        vk = win32api.VkKeyScan(key) & 0xFF
    else:
        raise Fail(f'unknown key {parts[-1]}, use Enter Tab Escape Backspace Delete Up Down Left Right Home End F1-F12 or one character')
    return mods, vk


def send_combo(combo):
    mods, vk = parse_combo(combo)
    for m in mods:
        win32api.keybd_event(m, 0, 0, 0)
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, 2, 0)
    for m in reversed(mods):
        win32api.keybd_event(m, 0, 2, 0)


def post_key(hwnd, combo):
    """Background key: posted straight to the window, no focus change. Modifiers can't be posted reliably."""
    mods, vk = parse_combo(combo)
    if mods:
        raise Fail(f'{combo} needs modifiers, which only work with --real (takes focus)')
    win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
    if vk == 0x0D:
        win32api.PostMessage(hwnd, win32con.WM_CHAR, 0x0D, 0)
    win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0xC0000001)


class KI(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [('ki', KI), ('pad', ctypes.c_byte * 32)]
    _fields_ = [('type', wintypes.DWORD), ('u', _U)]


def send_text(text):
    for ch in text:
        for flags in (4, 6):  # KEYEVENTF_UNICODE, + KEYUP
            i = INPUT(type=1)
            i.u.ki = KI(0, ord(ch), flags, 0, 0)
            user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def native_hwnd(n, h):
    try:
        x = n['el'].CurrentNativeWindowHandle
        return x or h
    except Exception:
        return h


# ---------- commands ----------
def c_list(st, a, f):
    fg = win32gui.GetForegroundWindow()
    rows = []
    for h in windows():
        mark = '*' if h == fg else ' '
        mn = ' [min]' if win32gui.IsIconic(h) else ''
        rows.append(f'{mark} {wid(h)} "{clip(win32gui.GetWindowText(h), 60)}" {proc_name(h)}{mn}')
    return '\n'.join(rows) or 'no windows'


def opts(f):
    return {'max': f.get('max'), 'raw': f.get('raw'), 'all': f.get('all'), 'interactive': f.get('i') or f.get('interactive'),
            'nofold': bool(f.get('expand') or f.get('raw'))}


def c_tree(st, a, f):
    h = find_window(a[0] if a else None)
    root = snapshot(h)
    refs = Refs(st, h)
    r = f.get('expand') or f.get('region')
    if r:
        rr = st['refs'].get(r)
        n = rr and rr['hwnd'] == h and find_node(root, rr['rid'])
        if not n:
            raise Fail(f'stale or unknown region ref {r}')
        root = n
    o = opts(f)
    if f.get('lines'):
        o['lines'] = int(f['lines'])
    return head(h) + '\n' + outline(root, refs, o)


def c_find(st, a, f):
    if len(a) < 2:
        raise Fail('find needs a window and text: win find notepad "Save" (or type:text, e.g. button:Save)')
    h = find_window(a[0])
    q = ' '.join(a[1:])
    role = None
    m = re.fullmatch(r'([a-z]+):(.*)', q)
    if m:
        role, q = m.group(1), m.group(2)
    q = q.lower()
    refs = Refs(st, h)
    hits = []
    for n in walk(snapshot(h)):
        if n['type'] in SKIP or (n['off'] and not f.get('all')):
            continue
        if role and n['type'] != role:
            continue
        hay = (n['name'] + ' ' + n['aid'] + ' ' + str(n['value'] or '')).lower()
        if q in hay and (interactive(n) or role or n['type'] in ('text', 'list', 'tree', 'pane', 'group', 'window', 'menu', 'toolbar')):
            hits.append(tok(n, refs) if interactive(n) or role else f'[{refs.get(n)} {n["type"]} "{clip(n["name"], 70)}"]')
        if len(hits) >= 30:
            break
    return '\n'.join(hits) or 'no match'


def c_click(st, a, f):
    h, n, _ = resolve(st, a[0] if a else None)
    if f.get('real') or f.get('double'):
        real_click(h, n, f.get('double'))
        return 'ok (real mouse click, took focus)'
    if f.get('right'):
        raise Fail('right click needs --real')
    if n['tog']:  # before Invoke: checkboxes often expose both, Toggle reports the new state
        p = pattern(n, 10015, U.IUIAutomationTogglePattern)
        p.Toggle()
        return 'ok ' + ['[ ]', '[x]', '[-]'][p.CurrentToggleState]
    if n['inv']:
        pattern(n, 10000, U.IUIAutomationInvokePattern).Invoke()
        return 'ok'
    if n['sel']:
        pattern(n, 10010, U.IUIAutomationSelectionItemPattern).Select()
        return 'ok selected'
    if n['exp']:
        p = pattern(n, 10005, U.IUIAutomationExpandCollapsePattern)
        (p.Collapse if p.CurrentExpandCollapseState == 1 else p.Expand)()
        return 'ok ' + ('expanded' if p.CurrentExpandCollapseState == 1 else 'collapsed')
    try:
        pattern(n, 10018, U.IUIAutomationLegacyIAccessiblePattern).DoDefaultAction()
        return 'ok (default action)'
    except Exception:
        raise Fail(f'{a[0]} has no background click (no Invoke/Toggle/Select pattern). Rerun with --real to use the mouse (takes focus)')


def c_type(st, a, f):
    if len(a) < 1:
        raise Fail('type needs a ref and text')
    h, n, _ = resolve(st, a[0])
    text = ' '.join(a[1:])
    if f.get('real'):
        front(h)
        n['el'].SetFocus()
        if f.get('clear'):
            send_combo('ctrl+a'); send_combo('delete')
        send_text(text)
        if f.get('enter'):
            send_combo('enter')
        return 'ok (real keyboard, took focus)'
    hw = native_hwnd(n, 0)
    if hw and hw != h and re.search(r'edit|richedit', win32gui.GetClassName(hw), re.I):
        # native edit: WM_SETTEXT sets text without the focus grab the UIA Win32 proxy does
        if f.get('append') and not f.get('clear'):
            ln = win32gui.SendMessage(hw, win32con.WM_GETTEXTLENGTH, 0, 0)
            buf = ctypes.create_unicode_buffer(ln + 1)
            user32.SendMessageW(hw, win32con.WM_GETTEXT, ln + 1, buf)
            text = buf.value + text
        user32.SendMessageW(hw, win32con.WM_SETTEXT, 0, ctypes.c_wchar_p(text))
        if f.get('enter'):
            post_key(hw, 'enter')
        return 'ok'
    if not n['val']:
        raise Fail(f'{a[0]} is not a settable field (no Value pattern). Rerun with --real to type with the keyboard (takes focus)')
    p = pattern(n, 10002, U.IUIAutomationValuePattern)
    if p.CurrentIsReadOnly:
        raise Fail(f'{a[0]} is read-only')
    new = text if f.get('clear') or not f.get('append') else (p.CurrentValue or '') + text
    p.SetValue(new)
    if f.get('enter'):
        post_key(native_hwnd(n, h), 'enter')
    return 'ok'


def win32_combo_select(n, want):
    """Native Win32/WinForms combobox: select by window messages, no popup and no focus."""
    hw = native_hwnd(n, 0)
    if not hw or 'combobox' not in win32gui.GetClassName(hw).lower():
        return None
    count = win32gui.SendMessage(hw, 0x146, 0, 0)  # CB_GETCOUNT
    items = []
    for i in range(count):
        ln = win32gui.SendMessage(hw, 0x149, i, 0)  # CB_GETLBTEXTLEN
        buf = ctypes.create_unicode_buffer(ln + 1)
        user32.SendMessageW(hw, 0x148, i, buf)  # CB_GETLBTEXT
        items.append(buf.value)
    idx = next((i for i, t in enumerate(items) if t.lower() == want.lower()), None)
    if idx is None:
        idx = next((i for i, t in enumerate(items) if want.lower() in t.lower()), None)
    if idx is None:
        raise Fail(f'no option "{want}". Options: ' + ' | '.join(clip(t, 30) for t in items[:30]))
    win32gui.SendMessage(hw, 0x14E, idx, 0)  # CB_SETCURSEL
    parent = win32gui.GetParent(hw)
    cid = win32gui.GetDlgCtrlID(hw) if hasattr(win32gui, 'GetDlgCtrlID') else user32.GetDlgCtrlID(hw)
    win32gui.SendMessage(parent, win32con.WM_COMMAND, (1 << 16) | (cid & 0xFFFF), hw)  # CBN_SELCHANGE
    return 'ok ' + items[idx]


def c_select(st, a, f):
    if len(a) < 2:
        raise Fail('select needs a ref and an option')
    h, n, root = resolve(st, a[0])
    want = ' '.join(a[1:]).lower()
    if n['type'] == 'combobox':
        r = win32_combo_select(n, ' '.join(a[1:]))
        if r:
            return r
    exp = None
    if n['exp']:
        exp = pattern(n, 10005, U.IUIAutomationExpandCollapsePattern)
        if exp.CurrentExpandCollapseState != 1:
            exp.Expand()
            time.sleep(0.2)
    ok = lambda x: x['sel'] and x['type'] in ('listitem', 'dataitem', 'treeitem', 'tabitem', 'radio')
    # options inside the target first (dropdown lists hang under the combobox), else anywhere in the window
    cand = [x for x in walk(snapshot(h, n['el'])) if ok(x)] or [x for x in walk(snapshot(h)) if ok(x)]
    hit = next((x for x in cand if x['name'].lower() == want), None) or next((x for x in cand if want in x['name'].lower()), None)
    if not hit:
        if exp:
            exp.Collapse()
        raise Fail(f'no option "{" ".join(a[1:])}". Options: ' + ' | '.join(clip(x['name'], 30) for x in cand[:20]))
    pattern(hit, 10010, U.IUIAutomationSelectionItemPattern).Select()
    if exp:
        try:
            exp.Collapse()
        except Exception:
            pass
    return 'ok ' + hit['name']


def c_key(st, a, f):
    if len(a) < 2:
        raise Fail('key needs a window (or ref) and a key: win key notepad ctrl+s')
    target, combo = a[0], a[1]
    if re.fullmatch(r'c\d+', target):
        h, n, _ = resolve(st, target)
        hw = native_hwnd(n, h)
    else:
        h = hw = find_window(target)
    if f.get('real'):
        front(h)
        if re.fullmatch(r'c\d+', target):
            n['el'].SetFocus()
        send_combo(combo)
        return 'ok (real keyboard, took focus)'
    post_key(hw, combo)
    return 'ok'


def c_text(st, a, f):
    h = find_window(a[0] if a else None)
    seen, out = set(), []
    for n in walk(snapshot(h)):
        if n['type'] in SKIP or n['off']:
            continue
        for t in (n['name'], n['value'] if isinstance(n['value'], str) else None):
            t = (t or '').strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    s = '\n'.join(out)
    mx = int(f.get('max') or 4000)
    return s[:mx] + (f'\n…+{(len(s) - mx) / 1000:.1f}k chars (--max N)' if len(s) > mx else '') if s else '(no text)'


def c_wait(st, a, f):
    if not a:
        raise Fail('wait needs a window title, or a window and text: win wait notepad "Saved"')
    end = time.time() + float(f.get('t') or 10)
    q = ' '.join(a[1:])
    while time.time() < end:
        try:
            h = find_window(a[0])
            if not q:
                return 'ok ' + head(h)[2:]
            hay = '\n'.join((n['name'] or '') + ' ' + str(n['value'] or '') for n in walk(snapshot(h)))
            if q.startswith('gone:') and q[5:] not in hay or not q.startswith('gone:') and q in hay:
                return 'ok'
        except Fail:
            pass
        time.sleep(0.3)
    raise Fail(f'timeout after {f.get("t") or 10}s waiting for {" ".join(a)}')


def c_launch(st, a, f):
    if not a:
        raise Fail('launch needs a command, e.g. win launch notepad')
    before = set(windows())
    subprocess.Popen(' '.join(a), shell=True)
    end = time.time() + float(f.get('t') or 15)
    while time.time() < end:
        time.sleep(0.3)
        new = [h for h in windows() if h not in before]
        if new:
            time.sleep(0.4)
            return 'ok ' + head(new[0])[2:]
    raise Fail('started, but no new window appeared. It may have reused an existing window: run win list')


def window_pattern(h):
    return UIA.ElementFromHandle(h).GetCurrentPattern(10009).QueryInterface(U.IUIAutomationWindowPattern)


def c_close(st, a, f):
    h = find_window(a[0] if a else None)
    try:
        window_pattern(h).Close()
    except Exception:
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
    time.sleep(0.3)
    return 'ok closed' if not win32gui.IsWindow(h) else 'ok close requested (window still open, maybe a save prompt: win tree it)'


def c_state(state):
    def run(st, a, f):
        h = find_window(a[0] if a else None)
        if state == 'focus':
            front(h)
        else:
            win32gui.ShowWindow(h, {'min': win32con.SW_MINIMIZE, 'max': win32con.SW_MAXIMIZE, 'restore': win32con.SW_SHOWNOACTIVATE}[state])
        return 'ok'
    return run


def c_shot(st, a, f):
    if not a:
        raise Fail('shot needs a window or ref')
    crop = None
    if re.fullmatch(r'c\d+', a[0]):
        h, n, _ = resolve(st, a[0])
        r = n['el'].CurrentBoundingRectangle
        crop = (r.left, r.top, r.right, r.bottom)
    else:
        h = find_window(a[0])
    import win32ui
    from PIL import Image
    was_min = win32gui.IsIconic(h)
    if was_min:  # minimized windows have no pixels: restore without activating, then put it back
        win32gui.ShowWindow(h, win32con.SW_SHOWNOACTIVATE)
        time.sleep(0.4)
    try:
        l, t, r_, b = win32gui.GetWindowRect(h)
        w, hh = r_ - l, b - t
        hdc = win32gui.GetWindowDC(h)
        mfc = win32ui.CreateDCFromHandle(hdc)
        sdc = mfc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc, w, hh)
        sdc.SelectObject(bmp)
        user32.PrintWindow(h, sdc.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT: works behind other windows
        info = bmp.GetInfo()
        img = Image.frombuffer('RGB', (info['bmWidth'], info['bmHeight']), bmp.GetBitmapBits(True), 'raw', 'BGRX', 0, 1)
        win32gui.DeleteObject(bmp.GetHandle()); sdc.DeleteDC(); mfc.DeleteDC(); win32gui.ReleaseDC(h, hdc)
    finally:
        if was_min:
            win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
    if crop:
        img = img.crop((crop[0] - l, crop[1] - t, crop[2] - l, crop[3] - t))
    out = f.get('o') or os.path.join(os.environ.get('TEMP', '.'), f'win-shot-{int(time.time() * 1000)}.png')
    img.save(out)
    return out


def c_do(st, a, f):
    out = []
    lines = [l.strip() for l in sys.stdin.read().splitlines() if l.strip() and not l.strip().startswith('#')]
    for i, line in enumerate(lines, 1):
        toks = shlex.split(line, posix=True)
        if toks and toks[0] == 'win':
            toks = toks[1:]
        cmd, pos, fl = parse(toks)
        if cmd not in CMDS or cmd in ('do', 'selftest'):
            out.append(f'> {line}\nerror line {i}: unknown or unsupported in do: {cmd}')
            raise Fail('\n'.join(out))
        try:
            out.append(f'> {line}\n' + CMDS[cmd](st, pos, fl))
        except Fail as e:
            out.append(f'> {line}\nerror line {i}: {e}')
            raise Fail('\n'.join(out))
    return '\n'.join(out)


def c_selftest(st, a, f):
    import selftest
    out, bad = selftest.run(st, CMDS, f)
    if bad:
        raise Fail(out)
    return out


HELP = f"""win <cmd> [args]   (docs: {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'README.md')})
  list                       top-level windows: * = foreground, w<id> "title" exe
  tree <win> [-i] [--all] [--region ref] [--expand ref] [--max N] [--raw]   control outline with refs
  find <win> <text|type:text>                  e.g. win find notepad button:Save
  click <ref> [--real] [--double]              background Invoke/Toggle/Select; --real uses the mouse
  type <ref> <text> [--clear] [--append] [--enter] [--real]
  select <ref> <option>      key <win|ref> <Enter|ctrl+s|...> [--real]
  text <win> [--max N]       wait <win> [text|gone:text] [--t s]
  launch <cmd>               close|focus|min|max|restore <win>
  shot <win|ref> [--o file]  do (commands on stdin)   selftest
<win> = w<id> from list, or part of the title, or exe name (notepad)."""

CMDS = {'list': c_list, 'tree': c_tree, 'find': c_find, 'click': c_click, 'type': c_type, 'select': c_select,
        'key': c_key, 'text': c_text, 'wait': c_wait, 'launch': c_launch, 'close': c_close, 'shot': c_shot,
        'focus': c_state('focus'), 'min': c_state('min'), 'max': c_state('max'), 'restore': c_state('restore'),
        'do': c_do, 'selftest': c_selftest, 'help': lambda st, a, f: HELP}
def keep_focus(fn):
    """Some UIA providers focus the app while acting. Background actions hand focus straight back."""
    def run(st, a, f):
        fg = win32gui.GetForegroundWindow()
        out = fn(st, a, f)
        if f.get('real') or f.get('double') or not fg or win32gui.GetForegroundWindow() == fg:
            return out
        try:
            win32api.keybd_event(0x12, 0, 0, 0)
            win32gui.SetForegroundWindow(fg)
            win32api.keybd_event(0x12, 0, 2, 0)
        except Exception:
            pass
        return out + (' (app grabbed focus, handed back)' if win32gui.GetForegroundWindow() == fg else ' (app grabbed focus)')
    return run


for _c in ('click', 'type', 'select', 'key'):
    CMDS[_c] = keep_focus(CMDS[_c])
BOOL = {'real', 'double', 'right', 'clear', 'append', 'enter', 'raw', 'all', 'i', 'interactive'}


def parse(argv):
    pos, fl = [], {}
    i = 0
    while i < len(argv):
        x = argv[i]
        if x.startswith('--') and len(x) > 2:
            k = x[2:]
            if k in BOOL:
                fl[k] = True
            else:
                i += 1
                fl[k] = argv[i] if i < len(argv) else ''
        elif x == '-i':
            fl['i'] = True
        else:
            pos.append(x)
        i += 1
    cmd = pos.pop(0) if pos else 'help'
    return cmd, pos, fl


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    cmd, pos, fl = parse(sys.argv[1:])
    if cmd not in CMDS:
        print(f'error: unknown command {cmd}, run win help', file=sys.stderr)
        return 1
    st = load()
    try:
        out = CMDS[cmd](st, pos, fl)
        print(out)

        return 0
    except Fail as e:
        msg = str(e)
        if cmd == 'do' or cmd == 'selftest':
            print(msg)
        else:
            print('error: ' + msg, file=sys.stderr)
        return 1
    except comtypes.COMError as e:
        print(f'error: UI Automation call failed ({e.args[1] if len(e.args) > 1 else e}). The element may be gone: run win tree again', file=sys.stderr)
        return 1
    finally:
        save(st)


if __name__ == '__main__':
    sys.exit(main())
