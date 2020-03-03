from io import BytesIO
from requests_html import AsyncHTMLSession
import requests
from .log import logger
from cachetools import TTLCache
from asyncache import cached
import asyncio
import json
from PIL import Image
from tenacity import retry, retry_if_exception_message, stop_after_attempt, wait_fixed, before_sleep_log
from .errors import RequestError, TokenExpiredError


class FeishuBot:
    def __init__(self,
                 app_id,
                 app_secret,
                 base_url=None,
                 token_ttl=3600,
                 user_ttl=300,
                 group_ttl=300):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url or ''
        self.session = AsyncHTMLSession()
        self.token_cache = TTLCache(1, token_ttl)
        self.group_cache = TTLCache(1, group_ttl)
        self.user_cache = TTLCache(32, user_ttl)

    @retry(stop=stop_after_attempt(3),
           wait=wait_fixed(1),
           retry=retry_if_exception_message(match='.*tenant_access_token.*'))
    async def request(self, method, endpoint, *args, **kwargs):
        url = f'{self.base_url}{endpoint}'
        no_auth = kwargs.pop('no_auth', False)
        if no_auth:
            # skip auth, for getting token itself
            headers = None
        else:
            # attach the token by default
            token = await self.get_access_token()
            headers = {'Authorization': f'Bearer {token}'}

        if 'json' in kwargs:
            logger.debug(f'payload: {json.dumps(kwargs["json"])}')

        resp: requests.Response = await self.session.request(method,
                                                             url,
                                                             *args,
                                                             headers=headers,
                                                             **kwargs)

        resp_json = resp.json()

        code = resp_json['code']
        msg = resp_json['msg']

        if code > 0:
            # documentation: https://open.feishu.cn/document/ukTMukTMukTM/ugjM14COyUjL4ITN
            if code == 99991663:
                # tenant access token error
                # invalidate the cache and retry again
                self.token_cache.expire()
                raise TokenExpiredError(code, msg)
            raise RequestError(code, msg)

        logger.debug(f'requested: {url=} {resp_json=}')

        return resp_json

    async def get(self, endpoint, *args, **kwargs):
        return await self.request('GET', endpoint, *args, **kwargs)

    async def post(self, endpoint, *args, **kwargs):
        return await self.request('POST', endpoint, *args, **kwargs)

    # refresh every 1 hour
    @cached(self.token_cache)
    async def get_access_token(self):
        logger.debug('getting new token')
        url = f'/auth/v3/app_access_token/internal/'
        resp = await self.post(url,
                               no_auth=True,
                               json={
                                   'app_id': self.app_id,
                                   'app_secret': self.app_secret
                               })

        return resp['tenant_access_token']

    @cached(self.user_cache)
    async def get_user_detail(self, open_id: str):
        url = f'/contact/v1/user/batch_get'
        resp = await self.get(url, params={'open_ids': open_id})
        return resp['data']['user_infos'][0]

    # refresh every 5 minutes
    @cached(self.group_cache)
    async def get_groups(self):
        resp = await self.get('/chat/v4/list')
        return resp['data']['groups']

    async def send_to_groups(self,
                             msg_type,
                             content=None,
                             card=None,
                             **kwargs):
        groups = await self.get_groups()
        tasks = []
        for g in groups:
            payload = {
                'chat_id': g['chat_id'],
                'msg_type': msg_type,
            }
            if card is not None:
                payload['card'] = card
                payload['update_multi'] = kwargs['is_shared']
            else:
                payload['content'] = content
            tasks.append(self.post('/message/v4/send/', json=payload))

        results = await asyncio.gather(*tasks)

        return zip(groups, results)

    async def send_text(self, text: str):
        """
        Send plain text
        """
        results = await self.send_to_groups('text', {'text': text})
        logger.debug(f'Sent {text=} to {[g["name"] for g, _ in results]}')

    async def upload_image(self, url, return_size=False):
        """
        Upload image of the given url
        """
        img_resp: requests.Response = await self.session.get(url)
        resp = await self.post('/image/v4/put/',
                               data={'image_type': 'message'},
                               files={"image": img_resp.content},
                               stream=True)

        image_key = resp['data']['image_key']
        logger.debug(f'uploaded image: {url=} {image_key=}')

        if return_size:
            img = Image.open(BytesIO(img_resp.content))
            return image_key, img.size
        else:
            return image_key

    async def send_image(self, image_url):
        """
        Send image
        """
        image_key = await self.upload_image(image_url)
        results = await self.send_to_groups('image', {'image_key': image_key})
        logger.debug(f'Sent {image_url=} to {[g["name"] for g, _ in results]}')

    async def send_post(self, title, content):
        """
        Send post(image+text)
        documentation: https://open.feishu.cn/document/ukTMukTMukTM/uMDMxEjLzATMx4yMwETM
        """
        results = await self.send_to_groups(
            'post', {'post': {
                'zh_cn': {
                    'title': title,
                    'content': content
                }
            }})
        logger.debug(f'Sent {title=} to {[g["name"] for g, _ in results]}')

    async def send_card(self, card, is_shared=False):
        """
        Send interactive card
        documentation: https://open.feishu.cn/document/ukTMukTMukTM/ugTNwUjL4UDM14CO1ATN 
        """
        assert isinstance(card, dict)
        results = await self.send_to_groups('interactive',
                                            card=card,
                                            is_shared=is_shared)
        logger.debug(f'Sent {card=} to {[g["name"] for g, _ in results]}')
