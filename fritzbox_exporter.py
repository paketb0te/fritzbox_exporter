"""
Module to fetch Metrics from a FritzBox and make them available to prometheus.
"""

import time
import random
import getpass
import logging
import fritzconnection
import prometheus_client
import yaml
import click


class FritzboxMetric:  # pylint: disable=too-few-public-methods
    """
    Contains all info needed to build metrics for prometheus.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        service: str,
        action: str,
        param: str,
        metric: prometheus_client.Metric,
    ) -> None:
        self.name = name
        self.service = service
        self.action = action
        self.param = param
        self.metric = metric
        if isinstance(metric, prometheus_client.Counter):
            self.old_value = 0


def setup(address: str, username: str, password: str, config: str):
    """
    Set up the connection to the fritzbox, read metrics
    and start the prometheus client server

    Args:
        address (str): IP / hostname of the device to monitor
        username (str): username to log in to the device
        password (str): password to log in to the device

    Returns:
        conn (FritzConnection): Connectionhandler for the device
        fritzbox_metrics (list): List of FritzboxMetric objects created from config
    """
    # set up the connection
    conn = fritzconnection.FritzConnection(
        address=address, user=username, password=password
    )
    # read configuration
    with open(file=config, mode="r") as file:
        metrics = dict(yaml.safe_load(file))
        logging.debug("Read configuration")
    # start server
    prometheus_client.start_http_server(port=8000)
    logging.info("Prometheus client server started.")
    # Set up metrics
    fritzbox_metrics = []
    for name, info in metrics.items():
        info = dict(info)
        service = info.get("service")
        action = info.get("action")
        param = info.get("param")
        logging.debug(
            "Read metric from config: %s. Service: %s, Action: %s, Parameter: %s",
            name,
            service,
            action,
            param,
        )
        metric_type = str(info.get("type")).lower()
        if metric_type == "gauge":
            logging.debug("Identified metric %s as type gauge", name)
            metric = prometheus_client.Gauge(
                name=name,
                documentation=f"Service: {service}, Action: {action}, Parameter: {param}",
            )
        if metric_type == "counter":
            logging.debug("Identified metric %s as type counter", name)
            metric = prometheus_client.Counter(
                name=name,
                documentation=f"Service: {service}, Action: {action}, Parameter: {param}",
            )
        fritzbox_metrics.append(
            FritzboxMetric(
                name=name, service=service, action=action, param=param, metric=metric
            )
        )
        logging.debug("Added %s to the list of monitored metrics.", name)

    return conn, fritzbox_metrics


def run(conn: fritzconnection.FritzConnection, fritzbox_metrics: list) -> None:
    """
    Poll the fritzbox and update metric values accordingly

    Args:
        conn (fritzconnection.FritzConnection): [description]
        fritzbox_metric (list): [description]
    """
    while True:
        for metric in fritzbox_metrics:
            response = conn.call_action(
                service_name=metric.service, action_name=metric.action
            )
            value = response.get(metric.param)
            if isinstance(metric.metric, prometheus_client.Gauge):
                metric.metric.set(value)
                logging.info("Updated %s to new value %d", metric.metric, value)
            if isinstance(metric.metric, prometheus_client.Counter):
                # This is a hack to work around the fact that we only can fetch the
                # total count of any counter from the fritzbox,
                # but would iddeally use a prometheus counter.
                # So we need to re-calculate the difference and then
                # increment the counter by that difference.
                diff = value - metric.old_value
                # crude overflow handling
                if diff < 0:
                    # if the counter on the fritzbox has overflown,
                    # we use value*2 as a close-enough estimate for the counter increase,
                    # since that is the mean expaected value
                    diff = value * 2
                metric.old_value = value
                metric.metric.inc(diff)
                logging.info("Incremented %s by %d", metric.metric, diff)
            # use randrange to distribute the requests a bit to avoid any lockstep issues
            time.sleep((10 + random.randrange(0, 10)) / len(fritzbox_metrics))


@click.command()
@click.option("--address", help="IP / hostname of the device to monitor.")
@click.option("--username", help="Username to log into the device.")
@click.option("--password", help="Password to log into the device.")
@click.option("--config", help="Path to a custom config file.")
@click.option(
    "--loglevel", help="Set the log level [CRITICAL, ERROR, WARNING, INFO, DEBUG]"
)
def main(address, username, password, config, loglevel):
    """
    Execution starts here.

    Args:
        address (str): IP / hostname of the device to monitor
        username (str): username to log in to the device
        password (str): password to log in to the device
    """
    # set up logging
    if loglevel:
        numeric_level = getattr(logging, loglevel.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError(f"Invalid log level: {loglevel}")
    else:
        numeric_level = logging.WARNING
    logging.basicConfig(format="%(asctime)s %(message)s", level=numeric_level)

    # Get credentials if they were not passed as options
    if not address:
        address = input("Please enter the IP / address of the device: ")
    if not username:
        username = input("Please enter the username to connect to the device: ")
    if not password:
        password = getpass.getpass()
    # set default config file
    if not config:
        config = "metrics.yml"

    conn, fritzbox_metrics = setup(
        address=address, username=username, password=password, config=config
    )
    run(conn=conn, fritzbox_metrics=fritzbox_metrics)


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
