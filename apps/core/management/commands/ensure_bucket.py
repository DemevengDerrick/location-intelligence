"""Create the private storage bucket if it is missing (local S3 stand-in only).

Production buckets (Cloudflare R2) are created and configured by hand or by infrastructure
code; the dev entrypoint runs this so a fresh `docker compose up` can store uploads.
"""

import time

from botocore.exceptions import ClientError, EndpointConnectionError
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the S3 bucket used for uploads if it does not exist (development)."

    def handle(self, *args, **options):
        client = getattr(getattr(default_storage, "connection", None), "meta", None)
        if client is None:
            self.stdout.write("Default storage is not S3; nothing to do.")
            return
        client = client.client
        bucket = default_storage.bucket_name
        for _attempt in range(30):  # the local S3 server can take ~20 s to start
            try:
                client.head_bucket(Bucket=bucket)
                self.stdout.write(f"Bucket {bucket} exists.")
                return
            except EndpointConnectionError:
                time.sleep(2)
            except ClientError:
                client.create_bucket(Bucket=bucket)
                self.stdout.write(self.style.SUCCESS(f"Created bucket {bucket}."))
                return
        self.stderr.write(f"Storage endpoint unreachable; bucket {bucket} not checked.")
