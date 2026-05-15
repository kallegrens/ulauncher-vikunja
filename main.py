import json
#import logging
#import os
from datetime import date
import requests
import re
import dateparser.search
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction

#_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')
# logging.basicConfig(handlers=[logging.FileHandler(_log_path, mode='w'), logging.StreamHandler()], level=logging.DEBUG)
#logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)

settings_read = False
all_projects = None
all_labels = None
default_project = None
config_error = None
priority_list = { 1: "Low", 2: "Medium", 3: "High", 4: "Urgent", 5: "DO NOW" }


def read_global_settings(extension, force=False):
    """Load extension preferences into globals; probe the API to catch misconfigurations."""
    global settings_read, vikunja_url, api_token, default_pid, auth_head
    global default_project, config_error, all_labels, all_projects
    if settings_read and not force:
        return
    #logger.info("Reading settings")
    config_error = None
    all_labels = None
    all_projects = None
    default_project = None
    vikunja_url = extension.preferences["vikunja_url"] + '/api/v1'
    api_token = extension.preferences["api_token"]
    default_pid = int(extension.preferences["default_project"])
    auth_head = {"Authorization": "Bearer %s" % api_token}
    # Probe API to validate config and pre-fill project cache
    try:
        r = requests.get('%s/projects' % vikunja_url, headers=auth_head, timeout=5)
        if r.status_code == 401:
            config_error = "Invalid API token — check your settings"
        elif r.status_code == 200:
            fetched = r.json()
            if isinstance(fetched, dict):
                fetched = [fetched]
            all_projects = fetched or []
        else:
            config_error = "Vikunja returned HTTP %d" % r.status_code
    except requests.exceptions.ConnectionError:
        config_error = "Cannot reach Vikunja at %s" % extension.preferences["vikunja_url"]
    except requests.exceptions.Timeout:
        config_error = "Vikunja connection timed out"
    settings_read = True


def filter_projects(title_contains):
    global all_projects
    if all_projects is None:
        #logger.info("Fetching all projects")
        r = requests.get('%s/projects' % vikunja_url, headers=auth_head)
        if r.status_code == 200:
            fetched = r.json()
            if isinstance(fetched, dict):
                fetched = [fetched]
            all_projects = fetched or []
        else:
            all_projects = []
    title_contains = title_contains.replace('_', ' ').strip()
    if not title_contains:
        return all_projects[:10]
    return [p for p in all_projects if title_contains.lower() in p["title"].lower()][:10]


def get_default_project():
    global default_project
    if not default_project:
        r = requests.get('%s/projects/%d' % (vikunja_url, default_pid), headers=auth_head)
        #logger.info("Default Project ID: %d return code: %d" % (default_pid, r.status_code))
        if r.status_code == 200:
            default_project = [r.json()]
        else:
            default_project = []
    return default_project


def get_or_fetch_labels():
    """Return cached label list, fetching from API if needed."""
    global all_labels
    if all_labels is None:
        #logger.info("Fetching all labels")
        r = requests.get('%s/labels' % vikunja_url, headers=auth_head)
        if r.status_code == 200:
            fetched = r.json()
            if isinstance(fetched, dict):
                fetched = [fetched]
            all_labels = fetched or []
        else:
            all_labels = []
    return all_labels


def get_or_create_label(label_name):
    """Return ID for label_name, creating the label in Vikunja if it doesn't exist yet."""
    labels = get_or_fetch_labels()
    for label in labels:
        if label['title'].lower() == label_name.lower():
            return label['id']
    # Label not found — create it
    headers = dict(auth_head)
    headers['Content-Type'] = 'application/json'
    r = requests.put('%s/labels' % vikunja_url, headers=headers, data=json.dumps({'title': label_name}))
    if r.status_code == 201:
        new_label = r.json()
        all_labels.append(new_label)
        #logger.info("Created label '%s' with id %d" % (label_name, new_label['id']))
        return new_label['id']
    #logger.warning("Failed to create label '%s': %s" % (label_name, r.text))
    return None


def parse_input(text):
    """
    Extract labels (*word), priority (!1-5), and due date from task text.
    Returns dict with keys: title (str), labels (list), priority (int|None), due_date (datetime|None).
    """
    labels = []
    priority = None
    due_date = None

    # Extract labels: *word or *word_with_underscores
    for match in re.findall(r'\B\*\w+', text):
        labels.append(match[1:].replace('_', ' ').strip())
        text = text.replace(match, '')

    # Extract priority: !1 through !5 (not followed by another digit)
    priority_match = re.search(r'![1-5](?!\d)', text)
    if priority_match:
        priority = int(priority_match.group()[1:])
        text = text.replace(priority_match.group(), '')

    # Extract due date using dateparser
    due_match = re.search(r'(?:due)\s+(.*)', text, re.IGNORECASE)
    if due_match:
        due_str = due_match.group();
        date_results = dateparser.search.search_dates(
            due_str, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': False}
        )
        if date_results:
            date_str, date_obj = date_results[0]
            due_date = date_obj
            text = text.replace(due_str, '')

    title = re.sub(r' +', ' ', text).strip()
    return {'title': title, 'labels': labels, 'priority': priority, 'due_date': due_date}


def format_card_description(project_title, parsed):
    """Build the description line shown on a result card."""
    parts = ['Add to "%s"' % project_title]
    if parsed['labels']:
        parts.append('Labels: %s' % ', '.join(parsed['labels']))
    if parsed['priority']:
        parts.append('Priority: %s' % priority_list[parsed['priority']])
    if parsed['due_date']:
        if parsed['due_date'].year == date.today().year:
            parts.append('Due: %s' % parsed['due_date'].strftime('%a %b %d %H:%M'))
        else:
            parts.append('Due: %s' % parsed['due_date'].strftime('%a %b %d %H:%M, %Y'))
    return ' | '.join(parts)


class VikunjaExtension(Extension):

    def __init__(self):
        super(VikunjaExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())


class KeywordQueryEventListener(EventListener):

    def on_event(self, event, extension):
        """
        Fires on every keystroke after the trigger keyword. Parses the query for
        project (+), labels (*), priority (!), and due date, then renders one result
        card per matching project.
        """
        global all_projects, default_project
        items = []
        task_text = event.get_argument()

        if not task_text:
            # Fresh activation — force-reload settings and probe API
            read_global_settings(extension, True)
            if config_error:
                items.append(ExtensionResultItem(icon='images/vikunja.png',
                                                 name='Configuration Error',
                                                 description=config_error,
                                                 on_enter=HideWindowAction()))
                return RenderResultListAction(items)
            items.append(ExtensionResultItem(icon='images/vikunja.png',
                                             name='Please type task text ...',
                                             on_enter=HideWindowAction()))
            return RenderResultListAction(items)
        else:
            read_global_settings(extension)

        if config_error:
            items.append(ExtensionResultItem(icon='images/vikunja.png',
                                             name='Configuration Error',
                                             description=config_error,
                                             on_enter=HideWindowAction()))
            return RenderResultListAction(items)

        # Extract project search string (+word)
        for_projects = re.findall(r'\B\+\w+', task_text)
        projects = []
        project_string = None
        if for_projects:
            task_text = re.sub(r' +', ' ', task_text.replace(for_projects[0], '')).strip()
            if not task_text:
                items.append(ExtensionResultItem(icon='images/vikunja.png',
                                                 name='Please type task text ...',
                                                 on_enter=HideWindowAction()))
                return RenderResultListAction(items)
            project_string = for_projects[0][1:]
            projects = filter_projects(project_string)
        else:
            projects = get_default_project()

        if not projects:
            items.append(ExtensionResultItem(icon='images/vikunja.png',
                                             name='No projects like "%s" found!' % (project_string or ''),
                                             on_enter=HideWindowAction()))
            return RenderResultListAction(items)

        # Parse remaining text for labels, priority, due date
        parsed = parse_input(task_text)
        #logger.info("Parsed input: %s" % parsed)

        for project in projects:
            data = {
                'project_id': project["id"],
                'project_title': project["title"],
                'task_text': parsed['title'],
                'labels': parsed['labels'],
                'priority': parsed['priority'],
                'due_date': parsed['due_date'].astimezone().isoformat() if parsed['due_date'] else None,
            }
            description = format_card_description(project["title"], parsed)
            items.append(ExtensionResultItem(icon='images/vikunja.png',
                                             name='"%s"' % parsed['title'],
                                             description=description,
                                             on_enter=ExtensionCustomAction(data, keep_app_open=True)))

        return RenderResultListAction(items)


class ItemEnterEventListener(EventListener):

    def on_event(self, event, extension):
        """
        Fires when the user selects a result card. Creates the task in Vikunja,
        attaches any labels, then shows a success or error card.
        """
        data = event.get_data()
        read_global_settings(extension, True)
        headers = dict(auth_head)
        headers['Content-Type'] = 'application/json'

        payload = {'title': data['task_text']}
        if data.get('priority'):
            payload['priority'] = data['priority']
        if data.get('due_date'):
            payload['due_date'] = data['due_date']

        #logger.info("Task payload: %s" % payload)
        r = requests.put('%s/projects/%s/tasks' % (vikunja_url, data['project_id']),
                         headers=headers, data=json.dumps(payload))

        if r.status_code == 201:
            task = r.json()
            task_id = task['id']
            #logger.info("Task created with id %d" % task_id)

            # Attach labels
            for label_name in data.get('labels', []):
                label_id = get_or_create_label(label_name)
                if label_id:
                    lr = requests.put('%s/tasks/%s/labels' % (vikunja_url, task_id),
                                      headers=headers, data=json.dumps({'label_id': label_id}))
                    if lr.status_code != 201:
                        pass
                        #logger.warning("Failed to attach label '%s': %s" % (label_name, lr.text))

            return RenderResultListAction([ExtensionResultItem(icon='images/vikunja.png',
                                                               name='Added task "%s"' % data['task_text'],
                                                               description='To project "%s"' % data['project_title'],
                                                               on_enter=HideWindowAction())])
        else:
            #logger.error("Task creation failed: %s" % r.text)
            return RenderResultListAction([ExtensionResultItem(icon='images/vikunja.png',
                                                               name='Failed to add task "%s"' % data['task_text'],
                                                               description='To project "%s"' % data['project_title'],
                                                               on_enter=HideWindowAction())])


if __name__ == '__main__':
    VikunjaExtension().run()
