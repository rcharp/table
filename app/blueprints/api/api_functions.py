import re
import sys
import time
import pytz
import string
import random
import requests
import traceback
from datetime import datetime
from collections import defaultdict
from app.extensions import db
from sqlalchemy import exists, and_, or_, inspect
from flask import current_app
from importlib import import_module
from app.blueprints.page.date import get_dt_string
from flask_login import current_user


# Create a distinct integration id for the integration.
def generate_id(size=12, chars=string.digits):
    # Generate a random 12-character user id
    new_id = int(''.join(random.choice(chars) for _ in range(size)))

    return new_id


def print_traceback(e):
    traceback.print_tb(e.__traceback__)
    print(e)
