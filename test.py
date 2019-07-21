import asyncio
import os
import shutil
import ssl
import unittest
import uuid

from aiodnsresolver import (
    Resolver,
)
from lowhaio import (
    Pool,
    buffered,
)
from lowhaio_aws_sigv4_unsigned_payload import (
    signed,
)
from mobius3 import (
    Syncer,
)


def async_test(func):
    def wrapper(*args, **kwargs):
        future = func(*args, **kwargs)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(future)
    return wrapper


class TestIntegration(unittest.TestCase):

    def add_async_cleanup(self, coroutine, *args):
        loop = asyncio.get_event_loop()
        self.addCleanup(loop.run_until_complete, coroutine(*args))

    @async_test
    async def test_single_small_file_uploaded(self):
        delete_dir = create_directory('/s3-home-folder')
        self.add_async_cleanup(delete_dir)

        start, stop = syncer_for('/s3-home-folder')
        self.add_async_cleanup(stop)
        await start()

        filename = str(uuid.uuid4())
        with open(f'/s3-home-folder/{filename}', 'wb') as file:
            file.write(b'some-bytes')

        await await_upload()

        request, close = get_docker_link_and_minio_compatible_http_pool()
        self.add_async_cleanup(close)

        self.assertEqual(await object_body(request, filename), b'some-bytes')


def create_directory(path):
    async def delete_dir():
        shutil.rmtree(path)

    os.mkdir(path)

    return delete_dir


def get_docker_link_and_minio_compatible_http_pool():
    async def transform_fqdn(fqdn):
        return fqdn

    ssl_context = ssl.SSLContext()
    ssl_context.verify_mode = ssl.CERT_NONE

    return Pool(
        # 0x20 encoding does not appear to work with linked containers
        get_dns_resolver=lambda: Resolver(transform_fqdn=transform_fqdn),
        # We use self-signed certs locally
        get_ssl_context=lambda: ssl_context,
    )


def syncer_for(path):
    return Syncer(
        path, 'https://minio:9000/my-bucket', 'us-east-1',
        get_pool=get_docker_link_and_minio_compatible_http_pool,
    )


async def await_upload():
    await asyncio.sleep(1)


async def object_body(request, key):
    async def get_credentials_from_environment():
        return os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'], ()

    signed_request = signed(
        request, credentials=get_credentials_from_environment,
        service='s3', region='us-east-1',
    )
    _, _, body = await signed_request(b'GET', f'https://minio:9000/my-bucket/{key}')
    body_bytes = await buffered(body)
    return body_bytes
