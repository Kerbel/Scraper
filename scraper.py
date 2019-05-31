from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, render_template
from datetime import datetime, timedelta
from urllib.request import urlopen
from bs4 import BeautifulSoup
from peewee import *
import atexit
import json

DB_PATH = 'campagins.sqlite'
PAGE_TO_SCRAPE = 'https://www.kickstarter.com/discover/popular'

MAX_HOURS_EARLIER = 24
CAMPAIGNS_AMOUNT_TO_FETCH = 10
FETCH_INTERVAL_IN_SECONDS = 60 * 60

CAMPAIGN_DIV_JSON_ATTR = 'data-project'
CAMPAIGNS_DIVS_CLASS = 'js-react-proj-card'
CAMPAIGNS_DIVS_ATTRS = {'class': CAMPAIGNS_DIVS_CLASS}

MAIN_TEMPLATE = 'campaigns.html'
EXAGGERATED_TEMPLATE = 'user_exaggerated.html'
CAMPAIGNS_NOT_FOUND_TEMPLATE = 'campaigns_not_found.html'

app = Flask(__name__)
scheduler = BackgroundScheduler()
database = SqliteDatabase(DB_PATH, pragmas={'foreign_keys': 1})


class BaseModel(Model):
    class Meta:
        database = database


class Campaign(BaseModel):
    campaign_id = IntegerField(primary_key=True, unique=True)
    name = TextField()
    thumbnail_url = TextField()
    backers = IntegerField()
    money_raised = IntegerField()
    currency = TextField()


class PopularityHistory(BaseModel):
    id = AutoField()
    timestamp = DateTimeField('%Y-%m-%d %H:%M:%S')
    campaign = ForeignKeyField(Campaign)


def create_database():
    with database:
        database.create_tables([Campaign, PopularityHistory])


def insert_campaign_object(campaign):
    try:
        with database.atomic():
            Campaign.create(campaign_id=campaign['id'],
                            name=campaign['name'],
                            thumbnail_url=campaign['photo']['thumb'],
                            backers=campaign['backers_count'],
                            money_raised=campaign['pledged'],
                            currency=campaign['currency'])

    except IntegrityError:
        database.rollback()

    except Exception as e:
        database.rollback()
        print('There was an error:', e)


def insert_popularity_history_record(campaign_id):
    try:
        with database.atomic():
            PopularityHistory.create(
                timestamp=datetime.now(),
                campaign=campaign_id
            )

    except Exception as e:
        database.rollback()
        print('There was an error:', e)


def scrape_divs_from_page(url, attrs_to_search):
    page = urlopen(PAGE_TO_SCRAPE)
    soup = BeautifulSoup(page, 'html.parser')
    divs = soup.findAll('div', attrs=attrs_to_search)
    return divs


def convert_divs_to_campaigns_list(divs):
    campaigns = []

    for div in divs:
        if len(campaigns) < CAMPAIGNS_AMOUNT_TO_FETCH:
            campaign = json.loads(div.attrs[CAMPAIGN_DIV_JSON_ATTR])
            campaigns.append(campaign)

    return campaigns


def download_campaigns():
    campaigns_divs = scrape_divs_from_page(PAGE_TO_SCRAPE, CAMPAIGNS_DIVS_ATTRS)
    campaigns = convert_divs_to_campaigns_list(campaigns_divs)

    for campaign in campaigns:
        insert_campaign_object(campaign)
        insert_popularity_history_record(campaign['id'])


def schedule_download():
    scheduler.add_job(func=download_campaigns,
                      trigger='interval',
                      seconds=FETCH_INTERVAL_IN_SECONDS)


def get_records_by_time(hours_earlier):
    return (PopularityHistory
            .select()
            .where(PopularityHistory
                   .timestamp
                   .between(datetime.now() - timedelta(hours=hours_earlier),
                            datetime.now() - timedelta(hours=hours_earlier - 1)))
            .join(Campaign)
            .group_by(PopularityHistory.campaign))


@app.route('/')
@app.route('/<int:hours_earlier>')
def render_relevant_template(hours_earlier=1):
    if hours_earlier > MAX_HOURS_EARLIER:
        return render_template(
            EXAGGERATED_TEMPLATE,
            max_hours_earlier=MAX_HOURS_EARLIER)

    popularity_history_records = get_records_by_time(hours_earlier)

    if popularity_history_records:
        return render_template(
            MAIN_TEMPLATE,
            records=popularity_history_records,
            max_hours_earlier=MAX_HOURS_EARLIER)

    return render_template(
        CAMPAIGNS_NOT_FOUND_TEMPLATE,
        hours_earlier=hours_earlier)


@app.before_first_request
def initialize_scraper():
    create_database()
    download_campaigns()
    schedule_download()

    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=1337)
