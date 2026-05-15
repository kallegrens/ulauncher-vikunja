# ULauncher Plugin for adding tasks to Vikunja

This plugin is for [ULauncher](https://ulauncher.io/) Application launcher for linux.

It allows to add tasks to self hosted To-Do app [Vikunja](https://vikunja.io/) with project lookup, labels, priorities and due dates (with natural language date parsing).

## Python prerequisites
For plugin to work python3 packages `requests`, `dateparser` and `tzlocal` have to be installed.

### Fedora, Red-Hat based
```bash
sudo dnf install python3-requests python3-dateparser python3-tzlocal
```

### Ubuntu, Debian based
```bash
sudo apt install python3-requests python3-dateparser python3-tzlocal
```

### Manjaro, Arch based
```bash
sudo pacman -S python-requests python-dateparser python-tzlocal 
```

## Manual Installation
- Download and extract latest release.

- Create folder if it does not exist:
`~/.local/share/ulauncher/extensions/`

- Move/Copy folder `vikunja-ulauncher-extension` to `~/.local/share/ulauncher/extensions/`

For example from terminal use:
```bash
mkdir -p ~/.local/share/ulauncher/extensions/
cp -R vikunja-ulauncher-extension ~/.local/share/ulauncher/extensions/
```

## Configuration
Open ulauncher configuration

- Change `Vikunja URL` to your hosted instance
- Change API Token to a token you have created in your Vikunja account
    - To create a token, open Vikunja app (Standalone or via browser)
    Your user => Settings => API Tokens => Create Token
    - These permissions for a token are required:
        - projects: read all, read one
        - tasks: create
        - labels: create, read all
        - tasksLabels: create

## Usage
- Open ulauncher
- type `vk` and space (if you have not changed Vikunja Task keyword in settings)
- type your to-do title

If you want to add entry to specific project:
    type `+` and part or full project title (Case insensitive), like '+inbox'

If you want to add labels use `*` symbol and label name like `*projects`, you can have multiple tags

Note: If you want to add a space in your porject search or label name, use underscore symbol '_' like *"+learn_vikunja"* would translate to project named *"learn vikunja"*)


If you want to set priority use '!' symbol followed by priority level 1 to 5
``` 
    1 - LOW
    2 - Medium
    3 - High
    4 - Urgent
    5 - DO NOW
```

If you want to set due date, at the end of the string type 'due ' and the date (and time if you want), input accepts relative dates like *'due in an hour'* or *'due tommorrow noon'* or *'due monday 8:15'* or other natural language date-time expressions like *'due on march 6th at 9:30'*

You will have a preview of your project, labels, priority and due date in Description box. If there are multiple projects, you will be allowed to choose one, select the one you want and press enter or click with a mouse.

Finally you will get a message if task was added successfuly or not.


