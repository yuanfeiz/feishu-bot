import pytest
from feishu_bot import FeishuBot
import pook


@pytest.mark.asyncio
@pook.on
async def test_upload_image():
    with pook.use(network=True):
        m1 = pook.get('http://foo.org/a.png', response_body="abc123")
        m2 = pook.put('api.feishu.com',
                      response_json={
                          'code': 0,
                          'data': {
                              'image_key': 'test-image-key'
                          }
                      })
        bot = FeishuBot('foo', 'bar', base_url='api.feishu.com')
        image_key = await bot.upload_image('http://foo.org/a.png')
        assert image_key == 'test-image-key'
