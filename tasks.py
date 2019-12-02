import os
import datetime
import editor
import uncurl
import requests
import pandas as pd
from invoke import task
from fake_useragent import UserAgent

from ratelimit import limits, sleep_and_retry
from xlrd import compdoc
from monkey.xlrd import compdoc as monkey_compdoc
from logger import get_logger

compdoc.CompDoc._locate_stream = monkey_compdoc.CompDoc._locate_stream


logger = get_logger(__name__)
USER_AGENT = UserAgent().random


def get_input(prompt=""):
    initial_message = ""
    if prompt:
        initial_message = "# {}\n\n".format(prompt)
    result = editor.edit(contents=str.encode(initial_message))
    i = "\n".join(
        line
        for line in result.decode("utf-8").split("\n")
        if not line.startswith("#") and len(line) > 0
    )
    if not i:
        raise RuntimeError("Empty input.")
    return i


CSRF_TOKEN_URL = "https://www.payhere.lk/account/remote/get_csrf_token"
EXPORT_URL = "https://www.payhere.lk/account/remote/export_excel_payments"
DEFAULT_HEADERS = {
    "Connection": "keep-alive",
    "Accept": "*/*",
    "Origin": "https://www.payhere.lk",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": USER_AGENT,
    "DNT": "1",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Referer": "https://www.payhere.lk/account/payments",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,ms;q=0.7",
}

session = requests.session()


@task
def dump(_, from_date, to_date=None, curl_command_file=None):
    def input_date(date_string):
        return datetime.datetime.strptime(date_string, "%Y/%m/%d").date()

    from_date = input_date(from_date)
    to_date = input_date(to_date) if to_date else datetime.date.today()

    logger.info("Collecting data from %s to %s", from_date, to_date)

    if curl_command_file:
        logger.info("Reading cookies from curl command dump in %s", curl_command_file)
        with open(curl_command_file, "r") as handle:
            curlcmd = handle.read()
    else:
        curlcmd = get_input("Paste the curl command from a logged in payhere session.")

    request_context = uncurl.parse_context(curlcmd)
    for key, value in request_context.cookies.items():
        session.cookies.set(key, value, path="/", domain=".payhere.lk")
    session.headers.update(DEFAULT_HEADERS)

    report_path = "report_{}_to_{}.csv".format(
        from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d")
    )
    save_dir = "exports/{}".format(int(datetime.datetime.now().timestamp()))
    try:
        os.makedirs(save_dir)
    except FileExistsError:
        pass

    if os.path.exists(report_path):
        os.remove(report_path)

    with open(report_path, "w") as report_fh:
        include_headers = True
        for exported_file in export_range(from_date, to_date, save_dir):
            xls_to_csv(exported_file, report_fh, include_headers)
            include_headers = False  # only include headers on the first one


def xls_to_csv(xls_file, file_handle, include_headers=False):
    xls = pd.ExcelFile(xls_file)
    parsed = xls.parse(sheetname="PayHere Payments", index_col=None, na_values=["NA"])
    parsed.to_csv(file_handle, header=include_headers)


def export_range(from_date, to_date, save_dir):
    for day_delta in reversed(range((to_date - from_date).days + 1)):
        file_name = export_data(
            from_date + datetime.timedelta(days=day_delta), save_dir
        )
        if file_name:
            yield file_name


@sleep_and_retry
@limits(calls=1, period=1)
def export_data(export_date, save_dir):
    logger.debug("Exporting data for date %s", export_date)

    logger.debug("Requesting csrf token.")
    csrf_response = session.get(CSRF_TOKEN_URL)
    csrf_response.raise_for_status()
    csrf_key, csrf_value = csrf_response.content.decode("utf8").split(",")

    formatted_date = export_date.strftime("%m/%d/%Y")
    get_params = {
        "from_date": formatted_date,
        "to_date": formatted_date,
        "key_word": "",
        csrf_key: csrf_value,
    }
    logger.debug("Requesting excel export.")
    export_response = session.post(EXPORT_URL, data=get_params)
    export_response.raise_for_status()
    download_url = export_response.content.decode("utf-8")

    if "account/application/export/" not in download_url:
        logger.warning(
            "Recieved unexpected export response for date %s. Skipping: %s",
            export_date,
            download_url,
        )
        return None

    logger.debug("Recieved export url for date %s: %s", export_date, download_url)
    download_file = "payhere_export_{}.xls".format(export_date.strftime("%Y-%m-%d"))
    with open(os.path.join(save_dir, download_file), "wb") as handle:
        logger.info("Writing the export to %s", handle.name)
        response = session.get(download_url, allow_redirects=True)
        handle.write(response.content)
        return handle.name
