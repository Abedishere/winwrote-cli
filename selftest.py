"""win selftest: builds a throwaway WinForms window that never takes focus, drives it in the
background, and checks that the foreground window never changed."""
import os, re, subprocess, tempfile, time
import win32gui

PS = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @"
using System.Windows.Forms;
public class TF : Form { protected override bool ShowWithoutActivation { get { return true; } } }
"@
$f = New-Object TF; $f.Text = 'winwrote selftest'; $f.Width = 420; $f.Height = 520
$f.StartPosition = 'Manual'; $f.Left = 40; $f.Top = 40; $f.TopMost = $false
$lbl = New-Object Windows.Forms.Label; $lbl.Text = 'waiting'; $lbl.Top = 10; $lbl.Left = 10; $lbl.Width = 380; $lbl.Name = 'out'
$tb = New-Object Windows.Forms.TextBox; $tb.Top = 40; $tb.Left = 10; $tb.Width = 200; $tb.AccessibleName = 'Query'
$cb = New-Object Windows.Forms.CheckBox; $cb.Text = 'Agree'; $cb.Top = 70; $cb.Left = 10
$co = New-Object Windows.Forms.ComboBox; $co.DropDownStyle = 'DropDownList'; $co.Top = 100; $co.Left = 10; $co.AccessibleName = 'Fruit'
[void]$co.Items.AddRange(@('Alpha','Beta','Gamma')); $co.SelectedIndex = 0
$bt = New-Object Windows.Forms.Button; $bt.Text = 'Go'; $bt.Top = 130; $bt.Left = 10
$bt.Add_Click({ $lbl.Text = 'clicked:' + $tb.Text + '-' + $cb.Checked + '-' + $co.SelectedItem })
$lb = New-Object Windows.Forms.ListBox; $lb.Top = 170; $lb.Left = 10; $lb.Width = 380; $lb.Height = 290; $lb.AccessibleName = 'Items'
1..300 | % { [void]$lb.Items.Add("Item $_") }
$f.Controls.AddRange(@($lbl,$tb,$cb,$co,$bt,$lb))
[Windows.Forms.Application]::Run($f)
'''


def run(st, CMDS, f):
    res = []

    def check(name, cond, got=''):
        res.append(('pass ' if cond else 'FAIL ') + name + ('' if cond else '\n     got: ' + str(got)[:400].replace('\n', '\n     ')))

    def c(cmd, *a, **fl):
        return CMDS[cmd](st, list(a), fl)

    def ref(s, rx):
        m = re.search(rx, s)
        return m.group(1) if m else None

    script = os.path.join(tempfile.gettempdir(), 'winwrote_selftest.ps1')
    with open(script, 'w', encoding='utf8') as fh:
        fh.write(PS)
    proc = subprocess.Popen(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', script])
    try:
        w = c('wait', 'winwrote selftest', t='20')
        check('window appears', w.startswith('ok'), w)
        fg = win32gui.GetForegroundWindow()
        t = c('tree', 'winwrote selftest')
        check('tree lists controls', all(x in t for x in ('button "Go"', 'checkbox "Agree"', 'edit "Query"', 'combobox "Fruit"')), t)
        check('tree hides offscreen list items', 'Item 200' not in t, t)
        check('tree shows text', 'waiting' in t, t)
        big = c('tree', 'winwrote selftest', all=True, max='1500')
        check('fold when over budget', re.search(r'…\+\d+ similar \(win tree w[0-9a-f]+ --expand c\d+\)', big), big)
        exp = ref(big, r'--expand (c\d+)')
        e = c('tree', 'winwrote selftest', expand=exp, all=True, max='60000') if exp else ''
        check('expand shows all items', 'Item 300' in e and 'similar' not in e, e[-300:])
        q = ref(c('find', 'winwrote selftest', 'Query'), r'\[(c\d+) edit')
        go = ref(c('find', 'winwrote selftest', 'button:Go'), r'\[(c\d+) button')
        ag = ref(c('find', 'winwrote selftest', 'checkbox:Agree'), r'\[(c\d+) checkbox')
        fr = ref(c('find', 'winwrote selftest', 'combobox:Fruit'), r'\[(c\d+) combobox')
        check('find returns refs', all((q, go, ag, fr)), (q, go, ag, fr))
        check('type', c('type', q, 'hello').startswith('ok'))
        check('toggle checkbox', c('click', ag).startswith('ok [x]'), c('tree', 'winwrote selftest', i=True))
        s = c('select', fr, 'Beta')
        check('select combobox option', s.startswith('ok Beta'), s)
        check('click button (Invoke)', c('click', go).startswith('ok'))
        check('wait for text', c('wait', 'winwrote selftest', 'clicked:hello-True-Beta', t='5') == 'ok')
        check('text', 'clicked:hello-True-Beta' in c('text', 'winwrote selftest'))
        check('type --append', c('type', q, ' world', append=True).startswith('ok') and 'hello world' in c('tree', 'winwrote selftest'))
        check('refs are stable across calls', ref(c('find', 'winwrote selftest', 'button:Go'), r'\[(c\d+) button') == go)
        try:
            c('click', 'c999999'); stale = ''
        except Exception as x:
            stale = str(x)
        check('unknown ref error', 'unknown ref' in stale, stale)
        check('foreground never changed', win32gui.GetForegroundWindow() == fg,
              f'{win32gui.GetWindowText(fg)!r} -> {win32gui.GetWindowText(win32gui.GetForegroundWindow())!r}')
        shot = c('shot', 'winwrote selftest', o=os.path.join(tempfile.gettempdir(), 'win-selftest.png'))
        check('shot writes png', os.path.exists(shot) and os.path.getsize(shot) > 1000, shot)
        lst = c('list')
        check('list shows window', 'winwrote selftest' in lst, lst[:300])
        check('close', c('close', 'winwrote selftest').startswith('ok closed'))
    except Exception as x:
        res.append(f'FAIL crashed: {type(x).__name__}: {x}')
    finally:
        try:
            proc.kill()
        except Exception:
            pass
    fails = sum(r.startswith('FAIL') for r in res)
    out = '\n'.join(res) + f'\n{"selftest FAILED" if fails else "selftest ok"} ({len(res) - fails}/{len(res)})'
    return out, fails
