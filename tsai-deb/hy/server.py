import os
import sys

sys.path.insert(0, "/usr/chindows")

from chindshell import meeting

app = meeting.create_app(
    basedir="/usr/chindows/hy",
    with_history=True,
    history_file=os.path.expanduser("~/.hy/history.json"),
)
