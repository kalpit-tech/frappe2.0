# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals
import functools
import frappe, re, os
from six import iteritems
from past.builtins import cmp
from frappe.utils import markdown

def delete_page_cache(path):
    cache = frappe.cache()
    cache.delete_value('full_index')
    groups = ("website_page", "page_context")
    if path:
        for name in groups:
            cache.hdel(name, path)
    else:
        for name in groups:
            cache.delete_key(name)

def find_first_image(html):
    m = re.finditer("""<img[^>]*src\s?=\s?['"]([^'"]*)['"]""", html)
    try:
        return next(m).groups()[0]
    except StopIteration:
        return None

def can_cache(no_cache=False):
    if frappe.conf.disable_website_cache or frappe.conf.developer_mode:
        return False
    if getattr(frappe.local, "no_cache", False):
        return False
    return not no_cache

def get_comment_list(doctype, name):
    return frappe.get_all('Comment',
            fields = ['name', 'creation', 'owner', 'comment_email', 'comment_by', 'content'],
            filters = dict(
                reference_doctype = doctype,
                reference_name = name,
                comment_type = 'Comment',
                published = 1
            ),
            order_by = 'creation asc')

def get_home_page():
    if frappe.local.flags.home_page:
        return frappe.local.flags.home_page

    def _get_home_page():
        home_page = None

        get_website_user_home_page = frappe.get_hooks('get_website_user_home_page')
        if get_website_user_home_page:
            home_page = frappe.get_attr(get_website_user_home_page[-1])(frappe.session.user)

        if not home_page:
            role_home_page = frappe.get_hooks("role_home_page")
            if role_home_page:
                for role in frappe.get_roles():
                    if role in role_home_page:
                        user = frappe.get_doc('User', frappe.session.user)
                        if(user.type=='brand'):
                            brand=user
                            if(frappe.get_doc('Company', brand.brand_name).enabled == 1):
                                home_page = role_home_page[role][-1]
                                break
                            elif(frappe.get_doc('Company', brand.brand_name).enabled == 0):
                                home_page = role_home_page['Disabled Brand User'][-1]
                                break
                        else:	
                            home_page = role_home_page[role][-1]
                            break

        if not home_page:
            home_page = frappe.get_hooks("home_page")
            if home_page:
                home_page = home_page[-1]

        if not home_page:
            home_page = frappe.db.get_value("Website Settings", None, "home_page") or "login"

        home_page = home_page.strip('/')

        return home_page

    return frappe.cache().hget("home_page", frappe.session.user, _get_home_page)

def is_signup_enabled():
    if getattr(frappe.local, "is_signup_enabled", None) is None:
        frappe.local.is_signup_enabled = True
        if frappe.utils.cint(frappe.db.get_value("Website Settings",
            "Website Settings", "disable_signup")):
                frappe.local.is_signup_enabled = False

    return frappe.local.is_signup_enabled

def cleanup_page_name(title):
    """make page name from title"""
    if not title:
        return title

    name = title.lower()
    name = re.sub('[~!@#$%^&*+()<>,."\'\?]', '', name)
    name = re.sub('[:/]', '-', name)

    name = '-'.join(name.split())

    # replace repeating hyphens
    name = re.sub(r"(-)\1+", r"\1", name)

    return name[:140]


def get_shade(color, percent):
    color, color_format = detect_color_format(color)
    r, g, b, a = color

    avg = (float(int(r) + int(g) + int(b)) / 3)
    # switch dark and light shades
    if avg > 128:
        percent = -percent

    # stronger diff for darker shades
    if percent < 25 and avg < 64:
        percent = percent * 2

    new_color = []
    for channel_value in (r, g, b):
        new_color.append(get_shade_for_channel(channel_value, percent))

    r, g, b = new_color

    return format_color(r, g, b, a, color_format)


def detect_color_format(color):
    if color.startswith("rgba"):
        color_format = "rgba"
        color = [c.strip() for c in color[5:-1].split(",")]

    elif color.startswith("rgb"):
        color_format = "rgb"
        color = [c.strip() for c in color[4:-1].split(",")] + [1]

    else:
        # assume hex
        color_format = "hex"

        if color.startswith("#"):
            color = color[1:]

        if len(color) == 3:
            # hex in short form like #fff
            color = "{0}{0}{1}{1}{2}{2}".format(*tuple(color))

        color = [int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), 1]

    return color, color_format


def get_shade_for_channel(channel_value, percent):
    v = int(channel_value) + int(int('ff', 16) * (float(percent)/100))
    if v < 0:
        v=0
    if v > 255:
        v=255

    return v


def format_color(r, g, b, a, color_format):
    if color_format == "rgba":
        return "rgba({0}, {1}, {2}, {3})".format(r, g, b, a)

    elif color_format == "rgb":
        return "rgb({0}, {1}, {2})".format(r, g, b)

    else:
        # assume hex
        return "#{0}{1}{2}".format(convert_to_hex(r), convert_to_hex(g), convert_to_hex(b))


def convert_to_hex(channel_value):
    h = hex(channel_value)[2:]

    if len(h) < 2:
        h = "0" + h

    return h

def abs_url(path):
    """Deconstructs and Reconstructs a URL into an absolute URL or a URL relative from root '/'"""
    if not path:
        return
    if path.startswith('http://') or path.startswith('https://'):
        return path
    if path.startswith('data:'):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return path

def get_toc(route, url_prefix=None, app=None):
    '''Insert full index (table of contents) for {index} tag'''
    from frappe.website.utils import get_full_index

    full_index = get_full_index(app=app)

    return frappe.get_template("templates/includes/full_index.html").render({
            "full_index": full_index,
            "url_prefix": url_prefix or "/",
            "route": route.rstrip('/')
        })

def get_next_link(route, url_prefix=None, app=None):
    # insert next link
    next_item = None
    route = route.rstrip('/')
    children_map = get_full_index(app=app)
    parent_route = os.path.dirname(route)
    children = children_map.get(parent_route, None)

    if parent_route and children:
        for i, c in enumerate(children):
            if c.route == route and i < (len(children) - 1):
                next_item = children[i+1]
                next_item.url_prefix = url_prefix or "/"

    if next_item:
        if next_item.route and next_item.title:
            html = ('<p class="btn-next-wrapper">' + frappe._("Next")\
                +': <a class="btn-next" href="{url_prefix}{route}">{title}</a></p>').format(**next_item)

            return html

    return ''

def get_full_index(route=None, app=None):
    """Returns full index of the website for www upto the n-th level"""
    from frappe.website.router import get_pages

    if not frappe.local.flags.children_map:
        def _build():
            children_map = {}
            added = []
            pages = get_pages(app=app)

            # make children map
            for route, page_info in iteritems(pages):
                parent_route = os.path.dirname(route)
                if parent_route not in added:
                    children_map.setdefault(parent_route, []).append(page_info)

            # order as per index if present
            for route, children in children_map.items():
                if not route in pages:
                    # no parent (?)
                    continue

                page_info = pages[route]
                if page_info.index or ('index' in page_info.template):
                    new_children = []
                    page_info.extn = ''
                    for name in (page_info.index or []):
                        child_route = page_info.route + '/' + name
                        if child_route in pages:
                            if child_route not in added:
                                new_children.append(pages[child_route])
                                added.append(child_route)

                    # add remaining pages not in index.txt
                    _children = sorted(children, key = functools.cmp_to_key(lambda a, b: cmp(
                        os.path.basename(a.route), os.path.basename(b.route))))

                    for child_route in _children:
                        if child_route not in new_children:
                            if child_route not in added:
                                new_children.append(child_route)
                                added.append(child_route)

                    children_map[route] = new_children

            return children_map

        children_map = frappe.cache().get_value('website_full_index', _build)

        frappe.local.flags.children_map = children_map

    return frappe.local.flags.children_map

def extract_title(source, path):
    '''Returns title from `&lt;!-- title --&gt;` or &lt;h1&gt; or path'''
    title = extract_comment_tag(source, 'title')

    if not title and "<h1>" in source:
        # extract title from h1
        match = re.findall('<h1>([^<]*)', source)
        title = match[0].strip()[:300]

    if not title:
        # make title from name
        title = os.path.basename(path.rsplit('.', )[0].rstrip('/')).replace('_', ' ').replace('-', ' ').title()

    return title

def extract_comment_tag(source, tag):
    '''Extract custom tags in comments from source.

    :param source: raw template source in HTML
    :param title: tag to search, example "title"
    '''

    if "<!-- {0}:".format(tag) in source:
        return re.findall('<!-- {0}:([^>]*) -->'.format(tag), source)[0].strip()
    else:
        return None


def add_missing_headers():
    '''Walk and add missing headers in docs (to be called from bench execute)'''
    path = frappe.get_app_path('erpnext', 'docs')
    for basepath, folders, files in os.walk(path):
        for fname in files:
            if fname.endswith('.md'):
                with open(os.path.join(basepath, fname), 'r') as f:
                    content = frappe.as_unicode(f.read())

                if not content.startswith('# ') and not '<h1>' in content:
                    with open(os.path.join(basepath, fname), 'w') as f:
                        if fname=='index.md':
                            fname = os.path.basename(basepath)
                        else:
                            fname = fname[:-3]
                        h = fname.replace('_', ' ').replace('-', ' ').title()
                        content = '# {0}\n\n'.format(h) + content
                        f.write(content.encode('utf-8'))

def get_html_content_based_on_type(doc, fieldname, content_type):
        '''
        Set content based on content_type
        '''
        content = doc.get(fieldname)

        if content_type == 'Markdown':
            content = markdown(doc.get(fieldname + '_md'))
        elif content_type == 'HTML':
            content = doc.get(fieldname + '_html')

        if content == None:
            content = ''

        return content
