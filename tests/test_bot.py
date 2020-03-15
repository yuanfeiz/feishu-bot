from feishu_bot import FeishuBot
import pytest
import pook
import asyncio
from datetime import datetime


async def test_init_bot():
    bot = FeishuBot('foo', 'bar')
    assert bot is not None


@pytest.mark.async_timeout(10)
async def test_upload_image():
    image_url = 'https://img.xiaoduanshijian.com/f28cc520be6ee16e8141-c66f9f10-27bb-1.png'
    endpoint_url = 'https://foo.com/api/image/v4/put/'
    get_token_url = 'https://foo.com/api/auth/v3/app_access_token/internal/'

    with pook.use():
        pook.get(image_url, response_body=b'abc')
        pook.post(get_token_url,
                  response_json={
                      'code': 0,
                      'msg': 'OK',
                      'tenant_access_token': 'test'
                  })
        pook.post(endpoint_url,
                  response_json={
                      'code': 0,
                      'msg': 'OK',
                      'data': {
                          'image_key': 'test-image-key'
                      }
                  })

        bot = FeishuBot('foo', 'bar', 'https://foo.com/api')
        image_key = await bot.upload_image(image_url)
    assert image_key == 'test-image-key'


async def test_send_text():
    with pook.use():
        get_token_mock = pook.post(
            'https://foo.com/api/auth/v3/app_access_token/internal/',
            response_json={
                'code': 0,
                'msg': 'OK',
                'tenant_access_token': 'test'
            })

        pook.get('https://foo.com/api/chat/v4/list').\
            header('Authorization', 'Bearer test').\
            reply(200).\
            json({'code': 0, 'msg': 'OK', 'data': {
                'groups': [
                    {'chat_id': 'chat_id_1', 'name': 'group_1'},
                    {'chat_id': 'chat_id_2', 'name': 'group_2'}
                ]
            }})

        send_message_mock = pook.post('https://foo.com/api/message/v4/send/',
                                      times=2,
                                      headers={'Authorization': 'Bearer test'},
                                      response_json={
                                          'code': 0,
                                          'msg': 'OK',
                                          'data': {
                                              'groups': [{
                                                  'chat_id': 'chat_id_1'
                                              }]
                                          }
                                      })

        bot = FeishuBot('foo', 'bar', 'https://foo.com/api')
        resp = await bot.send_text('hello world')
        assert send_message_mock.calls == 2
        assert get_token_mock.calls == 1


async def test_refresh_token():
    with pook.use():
        # Populate token with request
        get_token_mock_1 = pook.post(
            'https://foo.com/api/auth/v3/app_access_token/internal/',
            response_json={
                'code': 0,
                'msg': 'OK',
                'tenant_access_token': 'test'
            })

        pook.get('https://foo.com/api/chat/v4/list').\
            header('Authorization', 'Bearer test').\
            reply(200).\
            json({'code': 0, 'msg': 'OK', 'data': {
                'groups': [
                    {'chat_id': 'chat_id_1', 'name': 'group_1'},
                    {'chat_id': 'chat_id_2', 'name': 'group_2'}
                ]
            }})

        # Pass the first send text
        send_text_mock_1 = pook.post('https://foo.com/api/message/v4/send/',
                                     headers={'Authorization': 'Bearer test'},
                                     response_json={
                                         'code': 0,
                                         'msg': 'OK',
                                         'data': {}
                                     })
        # Fail the second send text with token expired
        send_text_mock_2 = pook.post('https://foo.com/api/message/v4/send/',
                                     headers={'Authorization': 'Bearer test'},
                                     response_json={
                                         'code': 99991663,
                                         'msg': 'token expired',
                                     })
        # Feed the valid token
        get_token_mock_2 = pook.post(
            'https://foo.com/api/auth/v3/app_access_token/internal/',
            response_json={
                'code': 0,
                'msg': 'OK',
                'tenant_access_token': 'test2'
            })

        # System would try again
        send_text_mock_3 = pook.post('https://foo.com/api/message/v4/send/',
                                     headers={'Authorization': 'Bearer test2'},
                                     response_json={
                                         'code': 0,
                                         'msg': 'OK',
                                         'data': {}
                                     })

        bot = FeishuBot('foo', 'bar', 'https://foo.com/api')
        resp = await bot.send_text('hello world')


async def test_auto_invalidate_token_cache():
    with pook.use():
        get_token_mock_1 = pook.post(
            'https://foo.com/api/auth/v3/app_access_token/internal/',
            response_json={
                'code': 0,
                'msg': 'OK',
                'tenant_access_token': 'test-token'
            })

        get_user_detail_mock = pook.get(
            'https://foo.com/api/contact/v1/user/batch_get',
            times=2,
            response_json={
                'code': 0,
                'msg': 'OK',
                'data': {
                    'user_infos': [{}]
                }
            })

        get_token_mock_2 = pook.post(
            'https://foo.com/api/auth/v3/app_access_token/internal/',
            response_json={
                'code': 0,
                'msg': 'OK',
                'tenant_access_token': 'test-token2'
            })

        bot = FeishuBot('foo', 'bar', 'https://foo.com/api', token_ttl=0.1)
        resp = await bot.get_user_detail('test-user-id')
        # Wait for token expiry
        await asyncio.sleep(.1)
        resp = await bot.get_user_detail('test-user-id')
        matches = get_user_detail_mock.matches
        assert len(matches) == 2
        assert matches[0].headers == {'Authorization': 'Bearer test-token'}
        assert matches[1].headers == {'Authorization': 'Bearer test-token2'}


async def test_update_group_name():
    with pook.use():
        get_token_mock_1 = pook.post(
            'https://foo.com/api/auth/v3/app_access_token/internal/',
            response_json={
                'code': 0,
                'msg': 'OK',
                'tenant_access_token': 'test-token'
            })
        pook.get('https://foo.com/api/chat/v4/list',
                 response_json={
                     'code': 0,
                     'msg': 'OK',
                     'data': {
                         'groups': [{
                             'chat_id': 'test_chat_id'
                         }]
                     }
                 })

        new_name = f'#名片审核 {datetime.now().isoformat()}'
        update_mock = pook.post('https://foo.com/api/chat/v4/update/',
                                response_json={
                                    'code': 0,
                                    'msg': 'OK',
                                })

        bot = FeishuBot('foo', 'bar', 'https://foo.com/api')
        groups = await bot.get_groups()
        g = groups[0]
        await bot.update_group_name(g['chat_id'], new_name)

        assert update_mock.calls == 1
