"""Private S3 storage whose signed URLs can target a different public endpoint.

In development the app reaches the local S3 server as http://s3:9090 (Docker network), but
the browser can only reach http://localhost:9090. Signing the download URL against the
public endpoint makes the link work in the browser while uploads still use the internal one.
In production AWS_S3_PUBLIC_ENDPOINT_URL is unset and behaviour is unchanged.
"""

import boto3
from botocore.config import Config
from django.conf import settings
from storages.backends.s3 import S3Storage
from storages.utils import clean_name


class PrivateS3Storage(S3Storage):
    _public_client = None

    def url(self, name, parameters=None, expire=None, http_method=None):
        public_endpoint = getattr(settings, "AWS_S3_PUBLIC_ENDPOINT_URL", "")
        if not public_endpoint:
            return super().url(name, parameters=parameters, expire=expire, http_method=http_method)
        if self._public_client is None:
            self._public_client = boto3.client(
                "s3",
                endpoint_url=public_endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region_name,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
        params = {"Bucket": self.bucket_name, "Key": self._normalize_name(clean_name(name))}
        params.update(parameters or {})
        return self._public_client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expire or self.querystring_expire
        )
