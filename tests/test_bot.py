from feishu_bot import FeishuBot
from aioresponses import aioresponses
import pytest


async def test_init_bot():
    bot = FeishuBot('foo', 'bar')
    assert bot is not None


@pytest.fixture()
def mocked():
    with aioresponses() as m:
        yield m


@pytest.mark.async_timeout(10)
async def test_upload_image(mocked):
    image_url = 'https://img.xiaoduanshijian.com/f28cc520be6ee16e8141-c66f9f10-27bb-1.png'
    endpoint_url = 'https://foo.com/api/image/v4/put/'
    get_token_url = 'https://foo.com/api/auth/v3/app_access_token/internal/'

    def callback(*args, **kwargs):
        print(f'{args=}, {kwargs=}')

    mocked.get(image_url, status=200, body=b'abc')
    mocked.post(get_token_url,
                status=200,
                payload={
                    'code': 0,
                    'msg': 'OK',
                    'tenant_access_token': 'test'
                },
                repeat=True)
    mocked.post(endpoint_url,
                status=200,
                payload={
                    'code': 0,
                    'msg': 'OK',
                    'data': {
                        'image_key': 'test-image-key'
                    }
                },
                callback=callback)

    bot = FeishuBot('foo', 'bar', 'https://foo.com/api')
    iamge_key = await bot.upload_image(image_url)
    assert iamge_key == 'test-image-key'