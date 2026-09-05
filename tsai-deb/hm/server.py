import os
import sys

sys.path.insert(0, "/usr/chindows")

from chindshell import meeting

app = meeting.create_app(basedir="/usr/chindows/hm", with_history=False)
