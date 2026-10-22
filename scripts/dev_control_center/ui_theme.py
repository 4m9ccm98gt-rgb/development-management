"""Shared DCC container/scrollbar styles, independent of the active native theme.

Copy clam drawing elements only. Never select a global theme here. Manager can
use namespaced styles; default styles cover future DCC container widgets too.
"""
def _copy(style, target, source):
    if target not in style.element_names():
        style.element_create(target, 'from', 'clam', source)


def notebook_styles(style, name='TNotebook', prefix='DCC.Notebook'):
    from .app import DARK_BG, DARK_FIELD, DARK_FG, DARK_BORDER, DARK_SELECTION, DARK_DISABLED_FG
    for part in ('client', 'tab', 'padding', 'focus', 'label'):
        _copy(style, prefix+'.'+part, 'Notebook.'+part)
    style.layout(name, [(prefix+'.client', dict(sticky='nswe'))])
    style.layout(name+'.Tab', [(prefix+'.tab', dict(sticky='nswe', children=[
        (prefix+'.padding', dict(side='top', sticky='nswe', children=[
            (prefix+'.focus', dict(side='top', sticky='nswe', children=[
                (prefix+'.label', dict(side='top', sticky=''))]))]))]))])
    style.configure(name, background=DARK_BG, bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
    style.configure(name+'.Tab', background=DARK_FIELD, foreground=DARK_FG, bordercolor=DARK_BORDER,
                    lightcolor=DARK_BORDER, darkcolor=DARK_BORDER, focuscolor=DARK_FG, padding=(10, 5))
    style.map(name+'.Tab', background=[('disabled', DARK_FIELD), ('selected', DARK_SELECTION), ('active', DARK_BORDER), ('!selected', DARK_FIELD)],
              foreground=[('disabled', DARK_DISABLED_FG), ('selected', DARK_FG), ('active', DARK_FG), ('!selected', DARK_FG)],
              bordercolor=[('selected', DARK_BORDER), ('!selected', DARK_BORDER)],
              lightcolor=[('selected', DARK_BORDER), ('!selected', DARK_BORDER)],
              darkcolor=[('selected', DARK_BORDER), ('!selected', DARK_BORDER)])


def scrollbar_styles(style, namespace=''):
    from .app import DARK_BG, DARK_FIELD, DARK_FG, DARK_BORDER, DARK_SELECTION, DARK_DISABLED_FG
    for orientation, arrows, sides in (('Horizontal', ('leftarrow', 'rightarrow'), ('left', 'right')),
                                       ('Vertical', ('uparrow', 'downarrow'), ('top', 'bottom'))):
        name = (namespace+'.' if namespace else '') + orientation+'.TScrollbar'
        prefix = (namespace or 'DCC')+'.'+orientation+'.Scrollbar'
        for part in ('trough', 'thumb', *arrows):
            _copy(style, prefix+'.'+part, orientation+'.Scrollbar.'+part)
        style.layout(name, [(prefix+'.trough', dict(sticky='nswe', children=[
            (prefix+'.'+arrows[0], dict(side=sides[0], sticky='')),
            (prefix+'.'+arrows[1], dict(side=sides[1], sticky='')),
            (prefix+'.thumb', dict(expand=1, sticky='nswe'))]))])
        style.configure(name, background=DARK_FIELD, troughcolor=DARK_BG, arrowcolor=DARK_FG,
                        bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
        style.map(name, background=[('pressed', DARK_SELECTION), ('active', DARK_SELECTION), ('!active', DARK_FIELD)],
                  troughcolor=[('!active', DARK_BG), ('active', DARK_BG)],
                  arrowcolor=[('disabled', DARK_DISABLED_FG), ('!active', DARK_FG), ('active', DARK_FG)])


def configure_dark_containers(style):
    from .app import DARK_BG, DARK_FG, DARK_BORDER, DARK_FIELD, DARK_SELECTION, DARK_DISABLED_FG
    notebook_styles(style)
    scrollbar_styles(style)
    for name, source, target in (('TFrame', 'Frame.border', 'DCC.Frame.border'),
                                 ('TLabelframe', 'Labelframe.border', 'DCC.Labelframe.border')):
        _copy(style, target, source)
        style.layout(name, [(target, dict(sticky='nswe'))])
        style.configure(name, background=DARK_BG, bordercolor=DARK_BORDER,
                        lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
    style.configure('TLabelframe.Label', background=DARK_BG, foreground=DARK_FG)
    style.configure('DCC.LaneCard.TButton', background=DARK_FIELD, foreground=DARK_FG)
    style.map('DCC.LaneCard.TButton', background=[('selected', DARK_SELECTION), ('active', DARK_BORDER), ('!active', DARK_FIELD)],
              foreground=[('disabled', DARK_DISABLED_FG), ('!disabled', DARK_FG)])
