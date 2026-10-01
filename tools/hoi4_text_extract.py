#!/usr/bin/env python3
"""Extract readable focus / event / decision / national-spirit text from a HOI4 mod.

Built for reading the China writing (建制派 etc.) in 烈焰升腾 (The Fire Rises) and
潜龙腾渊, but works on any Hearts of Iron IV mod. Python 3.8+, standard library only.

1. See what is in the mod (focus trees, event namespaces, decision categories):

    python hoi4_text_extract.py --list "<...>/steamapps/workshop/content/394360/3504418504"

2. Dump the parts you want to a Markdown file:

    python hoi4_text_extract.py --tag CHI -o china.md "<...>/394360/3504418504"
    python hoi4_text_extract.py --tree china --namespace china -o china.md "<mod>"
    python hoi4_text_extract.py --keyword 乘风好去 "<mod>"

Several mod folders may be given, base mod first: later folders override earlier
ones (same file path, same localisation key), the way a submod loads on top.
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict

LOC_LINE = re.compile(r'^\s*([^\s#:"]+):\d*\s*"(.*)"\s*(?:#[^"]*)?$')
EVENT_TYPES = (
    'country_event', 'news_event', 'state_event', 'unit_leader_event',
    'operative_leader_event', 'event',
)
SHARED = '(shared) '


# ------------------------------------------------------------------------ files

def read_text(path):
    with open(path, 'rb') as f:
        data = f.read()
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode('utf-8', errors='replace')


def collect_files(mod_dirs, subdir, exts):
    """Relative path -> absolute path; later mod folders override earlier ones."""
    files = OrderedDict()
    for mod in mod_dirs:
        root = os.path.join(mod, subdir)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, names in os.walk(root):
            dirnames.sort()
            for name in sorted(names):
                if name.lower().endswith(exts):
                    abs_path = os.path.join(dirpath, name)
                    rel = os.path.relpath(abs_path, mod).replace(os.sep, '/').lower()
                    files.pop(rel, None)
                    files[rel] = abs_path
    return files


# ----------------------------------------------------------------- localisation

def read_loc_file(path, language):
    """[(key, raw text), ...] in file order, or None if the file is another language."""
    lines = read_text(path).splitlines()
    first = next((l.strip() for l in lines if l.strip() and not l.strip().startswith('#')), '')
    if first.split('#')[0].strip() != 'l_%s:' % language:
        return None
    return [m.groups() for m in map(LOC_LINE.match, lines) if m]


def loc_files(mod_dirs):
    """Localisation files of each folder; a folder without localisation/ is searched as is."""
    files = collect_files(mod_dirs, 'localisation', ('.yml',))
    for d in mod_dirs:
        if not os.path.isdir(os.path.join(d, 'localisation')):
            files.update(collect_files([d], '', ('.yml',)))
    return files


def load_localisation(mod_dirs, language):
    """Key -> raw text. Files under localisation/**/replace/ win over everything else."""
    loc, replace = {}, {}
    for rel, path in loc_files(mod_dirs).items():
        entries = read_loc_file(path, language)
        if entries:
            (replace if '/replace/' in '/' + rel else loc).update(entries)
    loc.update(replace)
    return loc


def clean(text, keep_codes=False):
    if text is None:
        return None
    text = text.replace('\\n', '\n').replace('\\"', '"')
    if not keep_codes:
        text = re.sub(r'§[A-Za-z0-9!]', '', text)          # colour codes
        text = re.sub(r'£[^\s£|]+(\|\d+)?£?', '', text)     # icons, incl. £GFX_banner£
    return text.strip()


# ---------------------------------------------------------------- script parser

TOKEN = re.compile(r'''
    (?P<ws>\s+) |
    (?P<comment>\#[^\n]*) |
    (?P<str>"(?:[^"\\]|\\.)*") |
    (?P<op><=|>=|!=|\?=|=|<|>) |
    (?P<open>\{) |
    (?P<close>\}) |
    (?P<word>[^\s={}<>!?"\#]+)
''', re.X)


def tokenize(text):
    pos = 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            pos += 1  # stray character
            continue
        pos = m.end()
        kind = m.lastgroup
        if kind in ('ws', 'comment'):
            continue
        val = m.group(kind)
        yield kind, val[1:-1] if kind == 'str' else val


def parse(text):
    """Clausewitz script -> nested lists of (key, value). Bare items are (None, value)."""
    tokens = list(tokenize(text))
    pos = 0

    def block():
        nonlocal pos
        items = []
        while pos < len(tokens):
            kind, val = tokens[pos]
            pos += 1
            if kind == 'close':
                return items
            if kind == 'open':
                items.append((None, block()))
            elif pos < len(tokens) and tokens[pos][0] == 'op':
                pos += 1
                if pos >= len(tokens):
                    break
                vkind, vval = tokens[pos]
                pos += 1
                items.append((val, block() if vkind == 'open' else vval))
            else:
                items.append((None, val))
        return items

    return block()


def get(items, key, default=None):
    for k, v in items:
        if k == key:
            return v
    return default


def get_all(items, key):
    return [v for k, v in items if k == key]


def mentions(items, word):
    """True if `word` appears anywhere in the block as a key or value (case-insensitive)."""
    word = word.lower()
    for k, v in items:
        if (k or '').lower() == word or (isinstance(v, str) and v.lower() == word):
            return True
        if isinstance(v, list) and mentions(v, word):
            return True
    return False


def text_keys(value):
    """``title = KEY`` or ``title = { text = KEY trigger = {...} }`` -> [KEY, ...]."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [k for k in get_all(value, 'text') if isinstance(k, str)]
    return []


def like(value, needles):
    value = str(value).lower()
    return any(n.lower() in value for n in needles)


# ------------------------------------------------------------------- extractors

def extract_focus_trees(mod_dirs):
    trees = []
    for rel, path in collect_files(mod_dirs, 'common/national_focus', ('.txt',)).items():
        root = parse(read_text(path))
        shared = [v for k, v in root if k == 'shared_focus' and isinstance(v, list)]
        if shared:
            trees.append({'id': SHARED + os.path.basename(rel), 'file': rel, 'country': [],
                          'shared_refs': [], 'focuses': shared})
        for tree in get_all(root, 'focus_tree'):
            if not isinstance(tree, list):
                continue
            tags = []
            country = get(tree, 'country', [])
            if isinstance(country, list):
                for _, v in country:
                    if isinstance(v, list):
                        tag = get(v, 'tag') or get(v, 'original_tag')
                        if isinstance(tag, str):
                            tags.append(tag)
            trees.append({
                'id': str(get(tree, 'id', '?')), 'file': rel, 'country': tags,
                'shared_refs': [v for v in get_all(tree, 'shared_focus') if isinstance(v, str)],
                'focuses': [f for f in get_all(tree, 'focus') if isinstance(f, list)],
            })
    return trees


def extract_events(mod_dirs):
    events = []
    for rel, path in collect_files(mod_dirs, 'events', ('.txt',)).items():
        for k, v in parse(read_text(path)):
            if k in EVENT_TYPES and isinstance(v, list):
                events.append({
                    'id': str(get(v, 'id', '?')), 'file': rel,
                    'title': [t for x in get_all(v, 'title') for t in text_keys(x)],
                    'desc': [t for x in get_all(v, 'desc') for t in text_keys(x)],
                    'options': [get(o, 'name') for o in get_all(v, 'option')
                                if isinstance(o, list) and isinstance(get(o, 'name'), str)],
                    'body': v,
                })
    return events


def extract_decisions(mod_dirs):
    categories = []
    for rel, path in collect_files(mod_dirs, 'common/decisions', ('.txt',)).items():
        if '/categories/' in rel:
            continue
        for cat, body in parse(read_text(path)):
            if cat and isinstance(body, list):
                categories.append({
                    'id': cat, 'file': rel, 'body': body,
                    'decisions': [k for k, v in body if k and isinstance(v, list)],
                })
    return categories


def extract_ideas(mod_dirs):
    ideas = []
    for rel, path in collect_files(mod_dirs, 'common/ideas', ('.txt',)).items():
        for k, v in parse(read_text(path)):
            if k != 'ideas' or not isinstance(v, list):
                continue
            for group, members in v:
                if not isinstance(members, list):
                    continue
                for idea, body in members:
                    if idea and isinstance(body, list):
                        ideas.append({'id': idea, 'group': group, 'file': rel, 'body': body})
    return ideas


# ------------------------------------------------------------------- selection

def pick_trees(trees, args):
    real = [t for t in trees if not t['id'].startswith(SHARED)]
    shared = [t for t in trees if t['id'].startswith(SHARED)]
    if not (args.tree or args.tag):
        return real + shared
    if args.tree:
        picked = [t for t in real if like(t['id'], args.tree) or like(t['file'], args.tree)]
    else:
        picked = [t for t in real if args.tag.upper() in (c.upper() for c in t['country'])]

    # shared focuses referenced by the picked trees, plus everything that builds on them
    wanted = {ref for t in picked for ref in t['shared_refs']}
    pool = [f for t in shared for f in t['focuses']]
    grew = True
    while grew:
        grew = False
        for f in pool:
            fid = get(f, 'id')
            if fid in wanted:
                continue
            prereqs = {v for p in get_all(f, 'prerequisite') if isinstance(p, list)
                       for k, v in p if k == 'focus'}
            if prereqs & wanted:
                wanted.add(fid)
                grew = True
    for t in shared:
        kept = [f for f in t['focuses'] if get(f, 'id') in wanted]
        if kept:
            picked.append(dict(t, focuses=kept))
    return picked


def namespace(event_id):
    return event_id.split('.')[0]


def pick_events(events, args):
    if args.namespace:
        return [e for e in events if like(namespace(e['id']), args.namespace) or like(e['file'], args.namespace)]
    if args.tag:
        tag = args.tag.lower()
        hit = {namespace(e['id']) for e in events
               if tag in namespace(e['id']).lower() or tag in e['file'] or mentions(e['body'], tag)}
        return [e for e in events if namespace(e['id']) in hit]
    return events


def pick_categories(categories, args):
    if args.category:
        return [c for c in categories if like(c['id'], args.category) or like(c['file'], args.category)]
    if args.tag:
        tag = args.tag.lower()
        return [c for c in categories
                if tag in c['id'].lower() or tag in c['file'] or mentions(c['body'], tag)]
    return categories


def walk(items):
    for k, v in items:
        yield k, v
        if isinstance(v, list):
            yield from walk(v)


def event_refs(items):
    """Event ids fired from a block: ``country_event = x.1`` or ``country_event = { id = x.1 }``."""
    refs = []
    for k, v in walk(items):
        if k in EVENT_TYPES:
            eid = get(v, 'id') if isinstance(v, list) else v
            if isinstance(eid, str):
                refs.append(eid)
    return refs


def idea_refs(items):
    refs = []
    for k, v in walk(items):
        if k in ('add_ideas', 'add_idea', 'idea'):
            if isinstance(v, str):
                refs.append(v)
            elif isinstance(v, list):
                refs.extend(x for kk, x in v if kk is None and isinstance(x, str))
    return refs


def mentions_any(items, keys, values):
    return any(k in keys and v in values for k, v in walk(items))


def follow(trees, events, categories, ideas):
    """Everything the picked focus trees lead to: events they fire (and the events
    those fire), events/decisions gated on their focuses, and spirits they grant.

    Shared focuses are the common trunk every route passes through, so they are not
    followed; otherwise one route would drag in every other route's content.
    """
    own = [t for t in trees if not t['id'].startswith(SHARED)]
    focus_ids = {get(f, 'id') for t in own for f in t['focuses']}
    focus_bodies = [f for t in own for f in t['focuses']]
    gate = ('has_completed_focus', 'focus')

    picked_cats = []
    for c in categories:
        if mentions_any(c['body'], gate, focus_ids) or any(mentions(b, c['id']) for b in focus_bodies):
            picked_cats.append(c)
            continue
        hits = [d for d in c['decisions'] if mentions_any(get(c['body'], d, []), gate, focus_ids)]
        if hits:
            picked_cats.append(dict(c, decisions=hits))
    decision_bodies = [get(c['body'], d, []) for c in picked_cats for d in c['decisions']]

    by_id = {e['id']: e for e in events}
    queue = [r for b in focus_bodies + decision_bodies for r in event_refs(b)]
    queue += [e['id'] for e in events if mentions_any(e['body'], gate, focus_ids)]
    seen = set()
    while queue:
        eid = queue.pop()
        if eid in seen or eid not in by_id:
            continue
        seen.add(eid)
        queue.extend(event_refs(by_id[eid]['body']))
    picked_events = [e for e in events if e['id'] in seen]

    wanted_ideas = {r for b in focus_bodies + decision_bodies + [e['body'] for e in picked_events]
                    for r in idea_refs(b)}
    picked_ideas = [i for i in ideas if i['id'] in wanted_ideas]
    return picked_events, picked_cats, picked_ideas


def pick_ideas(ideas, args):
    if args.tag:
        tag = args.tag.lower()
        return [i for i in ideas if tag in i['id'].lower() or tag in i['file']]
    return ideas


# ----------------------------------------------------------------------- output

def quote(text):
    return '\n'.join('> ' + l if l.strip() else '>' for l in text.split('\n'))


class Writer:
    def __init__(self, loc, keep_codes, keywords):
        self.loc = loc
        self.keep_codes = keep_codes
        self.keywords = keywords
        self.lines = []
        self.data = []

    def t(self, key):
        return clean(self.loc.get(key), self.keep_codes) if key else None

    def wanted(self, *texts):
        if not self.keywords:
            return True
        blob = '\n'.join(x for x in texts if x)
        return any(kw in blob for kw in self.keywords)

    def add(self, line=''):
        self.lines.append(line)

    def entry(self, title, key, paragraphs=(), bullets=()):
        if self.lines and self.lines[-1].startswith('- '):
            self.add()
        self.add('### %s  `%s`\n' % (title or key, key))
        for p in paragraphs:
            self.add(quote(p) + '\n')
        for b in bullets:
            self.add('- %s' % b)
        if bullets:
            self.add()


def to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def tree_order(focuses):
    """Sort focuses top-to-bottom, left-to-right as laid out in game
    (x/y are relative to ``relative_position_id`` when it is set)."""
    by_id = {get(f, 'id'): f for f in focuses}
    cache = {}

    def pos(fid, depth=0):
        if fid in cache:
            return cache[fid]
        f = by_id.get(fid)
        if f is None or depth > 50:
            return 0, 0
        x, y = to_int(get(f, 'x')), to_int(get(f, 'y'))
        parent = get(f, 'relative_position_id')
        if isinstance(parent, str) and parent in by_id:
            px, py = pos(parent, depth + 1)
            x, y = x + px, y + py
        cache[fid] = (x, y)
        return x, y

    return sorted(focuses, key=lambda f: (pos(get(f, 'id'))[1], pos(get(f, 'id'))[0]))


def write_focuses(w, trees, order='tree'):
    w.add('# 国策 National focuses\n')
    for tree in trees:
        entries = []
        focuses = tree_order(tree['focuses']) if order == 'tree' else tree['focuses']
        for f in focuses:
            fid = get(f, 'id')
            if not isinstance(fid, str):
                continue
            key = get(f, 'text') if isinstance(get(f, 'text'), str) else fid
            name = w.t(key) or w.t(fid)
            desc = w.t(key + '_desc') or w.t(fid + '_desc')
            if (name or desc) and w.wanted(name, desc, fid):
                entries.append((fid, name, desc))
        if not entries:
            continue
        w.add('## %s  `%s`\n' % (tree['id'], tree['file']))
        for fid, name, desc in entries:
            w.entry(name, fid, [desc] if desc else [])
            w.data.append({'kind': 'focus', 'tree': tree['id'], 'id': fid, 'name': name, 'desc': desc})


def write_events(w, events):
    w.add('# 事件 Events\n')
    by_ns = OrderedDict()
    for e in events:
        by_ns.setdefault(namespace(e['id']), []).append(e)
    for ns, items in by_ns.items():
        entries = []
        for e in items:
            titles = [x for x in map(w.t, e['title']) if x]
            descs = [x for x in map(w.t, e['desc']) if x]
            options = [w.t(k) or k for k in e['options']]
            if (titles or descs) and w.wanted(e['id'], *(titles + descs + options)):
                entries.append((e, titles, descs, options))
        if not entries:
            continue
        w.add('## %s\n' % ns)
        for e, titles, descs, options in entries:
            w.entry(' / '.join(titles), e['id'], descs, ['选项：' + o for o in options])
            w.data.append({'kind': 'event', 'id': e['id'], 'title': titles, 'desc': descs, 'options': options})


def write_decisions(w, categories):
    w.add('# 决议 Decisions\n')
    for cat in categories:
        entries = []
        for did in cat['decisions']:
            name, desc = w.t(did), w.t(did + '_desc')
            if (name or desc) and w.wanted(name, desc, did):
                entries.append((did, name, desc))
        if not entries:
            continue
        w.add('## %s  `%s`\n' % (w.t(cat['id']) or cat['id'], cat['id']))
        cat_desc = w.t(cat['id'] + '_desc')
        if cat_desc:
            w.add(quote(cat_desc) + '\n')
        for did, name, desc in entries:
            w.entry(name, did, [desc] if desc else [])
            w.data.append({'kind': 'decision', 'category': cat['id'], 'id': did, 'name': name, 'desc': desc})


def write_ideas(w, ideas):
    w.add('# 国家精神 National spirits\n')
    for idea in ideas:
        name, desc = w.t(idea['id']), w.t(idea['id'] + '_desc')
        if (name or desc) and w.wanted(name, desc, idea['id']):
            w.entry(name, idea['id'], [desc] if desc else [])
            w.data.append({'kind': 'idea', 'id': idea['id'], 'name': name, 'desc': desc})


EVENT_KEY = re.compile(r'^([A-Za-z_][\w]*\.\d+)\.(\w+)$')


def write_loc_only(w, files, language, file_filters):
    """Render localisation files on their own, in file order: ``X`` + ``X_desc`` as one
    entry, ``ns.N.t`` / ``.d`` / ``.a``... as one event, anything else as a line."""
    for rel, path in files.items():
        if file_filters and not like(rel, file_filters):
            continue
        entries = read_loc_file(path, language)
        if not entries:
            continue
        keys = OrderedDict(entries)
        blocks, events, used = [], OrderedDict(), set()
        for key in keys:
            m = EVENT_KEY.match(key)
            if m:
                ev = events.setdefault(m.group(1), {'t': [], 'd': [], 'o': []})
                part = m.group(2)
                slot = 't' if part in ('t', 'title') else 'd' if part.startswith('d') else 'o'
                if not ev['t'] and not ev['d'] and not ev['o']:
                    blocks.append(('event', m.group(1)))
                ev[slot].append(key)
            elif key.endswith('_desc') and key[:-5] in keys:
                continue
            else:
                blocks.append(('pair', key))
        lines_before, entries_before = len(w.lines), len(w.data)
        w.add('## %s\n' % rel)
        for kind, key in blocks:
            if kind == 'event':
                ev = events[key]
                titles = [x for x in map(w.t, ev['t']) if x]
                descs = [x for x in map(w.t, ev['d']) if x]
                options = [x for x in map(w.t, ev['o']) if x]
                if (titles or descs or options) and w.wanted(key, *(titles + descs + options)):
                    w.entry(' / '.join(titles), key, descs, ['选项：' + o for o in options])
                    w.data.append({'kind': 'event', 'id': key, 'title': titles, 'desc': descs, 'options': options})
            else:
                name, desc = w.t(key), w.t(key + '_desc')
                if not (name or desc) or not w.wanted(key, name, desc):
                    continue
                if desc:
                    w.entry(name, key, [desc])
                elif '\n' in name or len(name) > 60:
                    w.entry(None, key, [name])
                else:
                    w.add('- `%s` %s' % (key, name))
                w.data.append({'kind': 'loc', 'id': key, 'name': name, 'desc': desc})
        if len(w.data) == entries_before:
            del w.lines[lines_before:]
        else:
            w.add()


def print_overview(trees, events, categories, loc):
    print('Localisation keys loaded: %d' % len(loc))
    print('\nFocus trees  (id | country tags | focuses | file)')
    for t in trees:
        print('  %-42s %-14s %4d  %s' % (t['id'], ','.join(t['country']) or '-', len(t['focuses']), t['file']))
    print('\nEvent namespaces  (namespace | events | first file)')
    counts, first_file = defaultdict(int), {}
    for e in events:
        ns = namespace(e['id'])
        counts[ns] += 1
        first_file.setdefault(ns, e['file'])
    for ns in sorted(counts):
        print('  %-42s %4d  %s' % (ns, counts[ns], first_file[ns]))
    print('\nDecision categories  (id | decisions | file)')
    for c in categories:
        print('  %-42s %4d  %s' % (c['id'], len(c['decisions']), c['file']))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('mod_dirs', nargs='+', help='mod folders, base mod first, submods after')
    p.add_argument('--language', default='simp_chinese', help='localisation language (default: simp_chinese)')
    p.add_argument('--tag', help='only content tied to this country tag, e.g. CHI or PRC')
    p.add_argument('--tree', action='append', default=[], help='focus trees whose id/file contains this (repeatable)')
    p.add_argument('--namespace', action='append', default=[], help='event namespaces whose name/file contains this (repeatable)')
    p.add_argument('--category', action='append', default=[], help='decision categories whose id/file contains this (repeatable)')
    p.add_argument('--event', action='append', default=[], help='also include this exact event id, e.g. china.2000 (repeatable)')
    p.add_argument('--keyword', action='append', default=[], help='only entries whose text or id contains this (repeatable, any match)')
    p.add_argument('--only', choices=['focus', 'event', 'decision', 'idea'], action='append', help='limit to these sections (repeatable)')
    p.add_argument('--keep-codes', action='store_true', help='keep §Y colour codes and £icons')
    p.add_argument('--order', choices=['tree', 'file'], default='tree',
                   help='focus order: as laid out in the tree (default) or as written in the file')
    p.add_argument('--follow', action='store_true',
                   help='with --tree/--tag: also take the events, decisions and spirits those focus trees lead to')
    p.add_argument('--list', action='store_true', help='print focus trees / event namespaces / decision categories and exit')
    p.add_argument('--loc-only', action='store_true',
                   help='skip the scripts and print localisation files as they are (for text-only mods)')
    p.add_argument('--file', action='append', default=[],
                   help='with --loc-only: only localisation files whose path contains this (repeatable)')
    p.add_argument('-o', '--output', help='write Markdown to this file (default: stdout)')
    p.add_argument('--json', help='also write the entries as JSON to this file')
    args = p.parse_args(argv)

    for d in args.mod_dirs:
        if not os.path.isdir(d):
            p.error('not a folder: %s' % d)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    loc = load_localisation(args.mod_dirs, args.language)
    if args.loc_only:
        w = Writer(loc, args.keep_codes, args.keyword)
        write_loc_only(w, loc_files(args.mod_dirs), args.language, args.file)
        return finish(w, args)
    trees = extract_focus_trees(args.mod_dirs)
    events = extract_events(args.mod_dirs)
    categories = extract_decisions(args.mod_dirs)

    if args.list:
        print_overview(trees, events, categories, loc)
        return 0
    if args.follow and not (args.tree or args.tag):
        p.error('--follow needs --tree or --tag')

    ideas = extract_ideas(args.mod_dirs)
    picked_trees = pick_trees(trees, args)
    if args.follow:
        picked_events, picked_cats, picked_ideas = follow(picked_trees, events, categories, ideas)
        if args.namespace:
            extra = {e['id'] for e in pick_events(events, args)}
            picked_events = [e for e in events if e['id'] in extra or e in picked_events]
        if args.category:
            ids = {c['id'] for c in picked_cats}
            picked_cats += [c for c in pick_categories(categories, args) if c['id'] not in ids]
    else:
        picked_events = pick_events(events, args)
        picked_cats = pick_categories(categories, args)
        picked_ideas = pick_ideas(ideas, args)

    if args.event:
        ids = {e['id'] for e in picked_events}
        picked_events = picked_events + [e for e in events if e['id'] in args.event and e['id'] not in ids]

    sections = args.only or ['focus', 'event', 'decision', 'idea']
    w = Writer(loc, args.keep_codes, args.keyword)
    jobs = [
        ('focus', lambda: write_focuses(w, picked_trees, args.order)),
        ('event', lambda: write_events(w, picked_events)),
        ('decision', lambda: write_decisions(w, picked_cats)),
        ('idea', lambda: write_ideas(w, picked_ideas)),
    ]
    for name, job in jobs:
        if name in sections:
            lines_before, entries_before = len(w.lines), len(w.data)
            job()
            if len(w.data) == entries_before:  # drop the empty section header
                del w.lines[lines_before:]
    return finish(w, args)


def finish(w, args):
    out = '\n'.join(w.lines) + '\n'
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(out)
        print('wrote %d entries to %s' % (len(w.data), args.output), file=sys.stderr)
    else:
        sys.stdout.write(out)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(w.data, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
