import json
import re
from datetime import date

import dateparser.search
import requests
from ulauncher.api import Extension, ExtensionResult, effects
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction

priority_list = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent", 5: "DO NOW"}

settings_read = False
all_projects = None
all_labels = None
config_error = None
vikunja_url = None
api_token = None
auth_head = None
project_map = {}  # shortcut keyword (str) -> project_id (int)
project_cache = {}  # project_id (int) -> [project]


def read_global_settings(extension, force=False):
    global settings_read, vikunja_url, api_token, auth_head
    global project_map, config_error, all_labels, all_projects, project_cache
    if settings_read and not force:
        return
    config_error = None
    all_labels = None
    all_projects = None
    project_cache = {}
    vikunja_url = extension.preferences["vikunja_url"].rstrip("/") + "/api/v1"
    api_token = extension.preferences["api_token"]
    auth_head = {"Authorization": "Bearer %s" % api_token}

    raw = extension.preferences.get("project_map", "").strip()
    project_map = {}
    if raw:
        try:
            mapping = json.loads(raw)
            if isinstance(mapping, dict):
                for keyword, pid_value in mapping.items():
                    try:
                        project_map[keyword.strip().lower()] = int(pid_value)
                    except (ValueError, TypeError):
                        pass
        except (json.JSONDecodeError, ValueError):
            config_error = "Invalid JSON in Project Shortcuts setting"

    if not config_error:
        try:
            r = requests.get("%s/projects" % vikunja_url, headers=auth_head, timeout=5)
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
            config_error = (
                "Cannot reach Vikunja at %s" % extension.preferences["vikunja_url"]
            )
        except requests.exceptions.Timeout:
            config_error = "Vikunja connection timed out"
    settings_read = True


def filter_projects(title_contains):
    global all_projects
    if all_projects is None:
        r = requests.get("%s/projects" % vikunja_url, headers=auth_head)
        if r.status_code == 200:
            fetched = r.json()
            if isinstance(fetched, dict):
                fetched = [fetched]
            all_projects = fetched or []
        else:
            all_projects = []
    title_contains = title_contains.replace("_", " ").strip()
    if not title_contains:
        return all_projects[:10]
    return [p for p in all_projects if title_contains.lower() in p["title"].lower()][
        :10
    ]


def get_project_by_id(pid):
    if pid in project_cache:
        return project_cache[pid]
    r = requests.get("%s/projects/%d" % (vikunja_url, pid), headers=auth_head)
    if r.status_code == 200:
        result = [r.json()]
    else:
        result = []
    project_cache[pid] = result
    return result


def get_or_fetch_labels():
    global all_labels
    if all_labels is None:
        r = requests.get("%s/labels" % vikunja_url, headers=auth_head)
        if r.status_code == 200:
            fetched = r.json()
            if isinstance(fetched, dict):
                fetched = [fetched]
            all_labels = fetched or []
        else:
            all_labels = []
    return all_labels


def get_or_create_label(label_name):
    labels = get_or_fetch_labels()
    for label in labels:
        if label["title"].lower() == label_name.lower():
            return label["id"]
    headers = dict(auth_head)
    headers["Content-Type"] = "application/json"
    r = requests.put(
        "%s/labels" % vikunja_url,
        headers=headers,
        data=json.dumps({"title": label_name}),
    )
    if r.status_code == 201:
        new_label = r.json()
        all_labels.append(new_label)
        return new_label["id"]
    return None


def parse_input(text):
    labels = []
    priority = None
    due_date = None

    for match in re.findall(r"\B\*\w+", text):
        labels.append(match[1:].replace("_", " ").strip())
        text = text.replace(match, "")

    priority_match = re.search(r"![1-5](?!\d)", text)
    if priority_match:
        priority = int(priority_match.group()[1:])
        text = text.replace(priority_match.group(), "")

    due_match = re.search(r"(?:due)\s+(.*)", text, re.IGNORECASE)
    if due_match:
        due_str = due_match.group()
        date_results = dateparser.search.search_dates(
            due_str,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if date_results:
            _date_str, date_obj = date_results[0]
            due_date = date_obj
            text = text.replace(due_str, "")

    title = re.sub(r" +", " ", text).strip()
    return {
        "title": title,
        "labels": labels,
        "priority": priority,
        "due_date": due_date,
    }


def format_card_description(project_title, parsed):
    parts = ['Add to "%s"' % project_title]
    if parsed["labels"]:
        parts.append("Labels: %s" % ", ".join(parsed["labels"]))
    if parsed["priority"]:
        parts.append("Priority: %s" % priority_list[parsed["priority"]])
    if parsed["due_date"]:
        if parsed["due_date"].year == date.today().year:
            parts.append("Due: %s" % parsed["due_date"].strftime("%a %b %d %H:%M"))
        else:
            parts.append("Due: %s" % parsed["due_date"].strftime("%a %b %d %H:%M, %Y"))
    return " | ".join(parts)


def parse_shortcut_and_task(full_text):
    """
    Try to split the full input into (shortcut_keyword, remaining_task_text).
    If the first word matches a configured shortcut, return (keyword, rest).
    Otherwise return (None, full_text).
    """
    words = full_text.strip().split(None, 1)
    if not words:
        return None, full_text
    first = words[0].lower()
    if first in project_map:
        rest = words[1] if len(words) > 1 else ""
        return first, rest
    return None, full_text


class VikunjaExtension(Extension):
    def on_input(self, query_str, trigger_id):
        task_text = query_str

        if not task_text:
            read_global_settings(self, force=True)
            if config_error:
                return [
                    ExtensionResult(
                        icon="images/vikunja.png",
                        name="Configuration Error",
                        description=config_error,
                        on_enter=effects.close_window(),
                    )
                ]

            # Show configured shortcuts as a reference
            if project_map:
                shortcuts = ", ".join(sorted(project_map.keys()))
            else:
                shortcuts = "(none configured)"

            return [
                ExtensionResult(
                    icon="images/vikunja.png",
                    name="Please type task text ...",
                    description="Shortcuts: %s" % shortcuts,
                    on_enter=effects.close_window(),
                )
            ]

        read_global_settings(self)

        if config_error:
            return [
                ExtensionResult(
                    icon="images/vikunja.png",
                    name="Configuration Error",
                    description=config_error,
                    on_enter=effects.close_window(),
                )
            ]

        # Check for +project override first
        for_projects = re.findall(r"\B\+\w+", task_text)
        if for_projects:
            task_text = re.sub(
                r" +", " ", task_text.replace(for_projects[0], "")
            ).strip()
            if not task_text:
                return [
                    ExtensionResult(
                        icon="images/vikunja.png",
                        name="Please type task text ...",
                        on_enter=effects.close_window(),
                    )
                ]
            project_string = for_projects[0][1:]
            projects = filter_projects(project_string)
            parsed = parse_input(task_text)
        else:
            # Try to match first word as a shortcut keyword
            keyword, task_text = parse_shortcut_and_task(task_text)

            if keyword:
                # Shortcut matched — resolve to the configured project
                pid = project_map[keyword]
                projects = get_project_by_id(pid)
                if not projects:
                    return [
                        ExtensionResult(
                            icon="images/vikunja.png",
                            name='Project not found for shortcut "%s"' % keyword,
                            description="The configured project ID may be invalid",
                            on_enter=effects.close_window(),
                        )
                    ]
                parsed = parse_input(task_text)
            else:
                # No shortcut — check if the first word looks like a project name search
                # Fall back to showing all configured projects
                if not task_text.strip():
                    return [
                        ExtensionResult(
                            icon="images/vikunja.png",
                            name="Please type task text ...",
                            on_enter=effects.close_window(),
                        )
                    ]
                parsed = parse_input(task_text)
                # Use all configured projects
                pids = set(project_map.values())
                projects = []
                for pid in pids:
                    projects.extend(get_project_by_id(pid))
                # Deduplicate by id
                seen = set()
                unique = []
                for p in projects:
                    if p["id"] not in seen:
                        seen.add(p["id"])
                        unique.append(p)
                projects = unique

        if not projects:
            return [
                ExtensionResult(
                    icon="images/vikunja.png",
                    name='No projects like "%s" found!'
                    % (for_projects[0][1:] if for_projects else ""),
                    on_enter=effects.close_window(),
                )
            ]

        items = []
        for project in projects:
            data = {
                "project_id": project["id"],
                "project_title": project["title"],
                "task_text": parsed["title"],
                "labels": parsed["labels"],
                "priority": parsed["priority"],
                "due_date": parsed["due_date"].astimezone().isoformat()
                if parsed["due_date"]
                else None,
            }
            description = format_card_description(project["title"], parsed)
            items.append(
                ExtensionResult(
                    icon="images/vikunja.png",
                    name='"%s"' % parsed["title"],
                    description=description,
                    on_enter=ExtensionCustomAction(data, keep_app_open=True),
                )
            )
        return items

    def on_item_enter(self, data):
        read_global_settings(self, force=True)
        headers = dict(auth_head)
        headers["Content-Type"] = "application/json"

        payload = {"title": data["task_text"]}
        if data.get("priority"):
            payload["priority"] = data["priority"]
        if data.get("due_date"):
            payload["due_date"] = data["due_date"]

        r = requests.put(
            "%s/projects/%s/tasks" % (vikunja_url, data["project_id"]),
            headers=headers,
            data=json.dumps(payload),
        )

        if r.status_code == 201:
            task_id = r.json()["id"]
            for label_name in data.get("labels", []):
                label_id = get_or_create_label(label_name)
                if label_id:
                    requests.put(
                        "%s/tasks/%s/labels" % (vikunja_url, task_id),
                        headers=headers,
                        data=json.dumps({"label_id": label_id}),
                    )
            return [
                ExtensionResult(
                    icon="images/vikunja.png",
                    name='Added task "%s"' % data["task_text"],
                    description='To project "%s"' % data["project_title"],
                    on_enter=effects.close_window(),
                )
            ]

        return [
            ExtensionResult(
                icon="images/vikunja.png",
                name='Failed to add task "%s"' % data["task_text"],
                description='To project "%s"' % data["project_title"],
                on_enter=effects.close_window(),
            )
        ]


if __name__ == "__main__":
    VikunjaExtension().run()