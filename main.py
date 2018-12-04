# 前提条件 (Anaconda では不要)
# $ pip install flask
#
# 起動
# $ python webhook.py
#
# 必要なモジュールの読み込み
from flask import Flask, jsonify, abort, make_response, request, render_template
import urllib.request, json

# Flaskクラスのインスタンスを作成
# __name__は現在のファイルのモジュール名
api = Flask(__name__)

# Azure FACE API PersonGroupのId
PERSON_GROUP_ID = 'mycoworkers'

# <Azure Face API Key>をKEY 1の値に置き換え
FACE_API_SUBSCRIPTION_KEY = '<Azure Face API Key>'

# <ngrok URL>をngrokのURLに置き換え
NGROK_URL = '<ngrok URL>'

# <Slack Incoming Webhook URL>をWebhook URLの値に置き換え
SLACK_INCOMING_WEBHOOK_URL = '<Slack Incoming Webhook URL>'

# <Slack OAuth Access Token>をOAuth Access Tokenの値に置き換え
SLACK_OAUTH_ACCESS_TOKEN = '<Slack OAuth Access Token>'

# 動作確認用
@api.route('/', methods=['GET'])
def get():
    return render_template('index.html')
    #return make_response('Hello micro:bit !!!')

# IFTTTからコールされるwebhookアクション
@api.route('/faces', methods=['POST'])
def faces():
    if request.headers['Content-Type'] != 'application/octet-stream':
        print(request.headers['Content-Type'])
        return jsonify(res='error'), 400

    # 写真データ
    photo_data = request.data

    # 写真から顔を検出する
    headers = {
        'Ocp-Apim-Subscription-Key': FACE_API_SUBSCRIPTION_KEY,
        'Content-Type': 'application/octet-stream'
    }
    facedetect = urllib.request.Request(
        'https://japaneast.api.cognitive.microsoft.com/face/v1.0/detect',
        method='POST',
        data=photo_data,
        headers=headers
    )
    faceList = []
    with urllib.request.urlopen(facedetect) as response:
        response_body = response.read().decode("utf-8")
        faceList = json.loads(response_body)

    # 顔が検出できない場合
    if not faceList:
        print('Can not detect face.')
        return jsonify(err='Can not detect face.')

    # 先頭の人物のみ処理
    face = faceList[0]
    faceId = face['faceId']

    # faceIdをファイル名にして写真を保存
    with open('./static/photos/' + faceId + '.png' , 'wb') as f:
        f.write(photo_data)

    candidates = []
    # 写真に写っている顔を識別、初回はPersonGroupが存在しないのでSkipする
    if is_exists_person_group():
        obj = {
            'personGroupId': PERSON_GROUP_ID,
            "faceIds": [faceId]
        }
        headers = {
            'Ocp-Apim-Subscription-Key': FACE_API_SUBSCRIPTION_KEY,
            'Content-Type': 'application/json'
        }
        json_data = json.dumps(obj).encode("utf-8")
        faceidentity = urllib.request.Request(
            'https://japaneast.api.cognitive.microsoft.com/face/v1.0/identify',
            method='POST',
            data=json_data,
            headers=headers
        )
        with urllib.request.urlopen(faceidentity) as response:
            response_body = response.read().decode("utf-8")
            faceList = json.loads(response_body)
            candidates = faceList[0]['candidates']

    # Slackに投稿する写真のURL
    photo_url = NGROK_URL + '/static/photos/' + faceId + '.png'

    slack_message = ''
    if len(candidates) > 0:
        # 人物が識別できた場合は、人物の情報を取得してSlackに投稿
        get_person = urllib.request.Request(
            'https://japaneast.api.cognitive.microsoft.com/face/v1.0/persongroups/'+PERSON_GROUP_ID+'/persons/'+candidates[0]['personId'],
            headers=headers
        )
        with urllib.request.urlopen(get_person) as response:
            response_body = response.read().decode("utf-8")
            person = json.loads(response_body)

        slack_message = {
            'text': person['name'] + 'が入出しました。',
            'attachments': [{
                'text': person['name'],
                'image_url': photo_url
            }]
        }
    else:
        # 人物を識別できない場合は、登録フォームをSlackに投稿
        slack_message = {
            'text': '新しい人が入出しました。',
            'attachments': [{
                'text': 'この人は誰ですか？ メンバーから選択して下さい。',
                'image_url': photo_url,
                'fallback': 'メンバーを選択してください。',
                'color': '#3AA3E3',
                'attachment_type': 'default',
                'callback_id': 'select_simple_1234',
                'actions': [
                    {
                        'name': 'visitor',
                        'text': 'メンバーを選択',
                        'type': 'select',
                        'data_source': 'users'
                    }
                ]
            }]
        }

    # Slackにメッセージを投稿
    #  Slackへの投稿に失敗しても顔の検出に成功している場合には検出された顔を返すように例外処理
    try:
        post_data = urllib.parse.urlencode({'payload':json.dumps(slack_message)}).encode('utf-8')
        facedetect = urllib.request.Request(
            SLACK_INCOMING_WEBHOOK_URL,
            post_data
        )
        with urllib.request.urlopen(facedetect) as response:
            response_body = response.read().decode("utf-8")
            print(response_body)
    except urllib.error.HTTPError as err:
        print('Slackへの投稿に失敗しました:')
        print(err)
    except ValueError as err:
        print('Slack Webhookの設定に誤りがあります:')
        print(err)

    return jsonify(face)

# 新しい人物が入室してきた場合に、Slack上でユーザーを選択すると呼ばれるアクション
@api.route('/persons', methods=['POST'])
def postPersons():
    print(request.headers['Content-Type'])
    if request.headers['Content-Type'] != 'application/x-www-form-urlencoded':
        print(request.headers['Content-Type'])
        return jsonify(res='error'), 400

    # TODO: 実際はここで、token が正しいかチェックする

    payload = json.loads(request.form['payload'])

    # Slackから送信されたリクエスト本文から選択したユーザーのIdを取得
    slack_user_id = payload['actions'][0]['selected_options'][0]['value']
    print(slack_user_id)

    # Slack API users.info をコールして選択したユーザの名前を取得
    obj = {
        'token': SLACK_OAUTH_ACCESS_TOKEN,
        'user': slack_user_id
    }
    get_userinfo = urllib.request.Request(
        'https://slack.com/api/users.info',
        method='POST',
        data=urllib.parse.urlencode(obj).encode("utf-8")
    )
    with urllib.request.urlopen(get_userinfo) as response:
        response_body = response.read().decode("utf-8")
        print(response_body)
        user = json.loads(response_body)

    print(user['user']['name'])

    # PersonGroupがなければ作成
    if not is_exists_person_group():
        headers = {
            'Ocp-Apim-Subscription-Key': FACE_API_SUBSCRIPTION_KEY,
            'Content-Type': 'application/json'
        }
        obj = {
            'name': 'My Co-workers'
        }
        create_person = urllib.request.Request(
            'https://japaneast.api.cognitive.microsoft.com/face/v1.0/persongroups/'+PERSON_GROUP_ID,
            method='PUT',
            data=json.dumps(obj).encode("utf-8"),
            headers=headers
        )
        with urllib.request.urlopen(create_person) as response:
            response_body = response.read().decode("utf-8")
            print(response_body)

    # 新しいPersonをPersonGroupに作成
    headers = {
        'Ocp-Apim-Subscription-Key': FACE_API_SUBSCRIPTION_KEY,
        'Content-Type': 'application/json'
    }
    obj = {
        'name': user['user']['name'],
        'userData': slack_user_id
    }
    create_person = urllib.request.Request(
        'https://japaneast.api.cognitive.microsoft.com/face/v1.0/persongroups/'+PERSON_GROUP_ID+'/persons',
        method='POST',
        data=json.dumps(obj).encode("utf-8"),
        headers=headers
    )
    with urllib.request.urlopen(create_person) as response:
        response_body = response.read().decode("utf-8")
        print(response_body)
        person = json.loads(response_body)

    # 写真をPersonに追加
    obj = {
        'url': payload['original_message']['attachments'][0]['image_url'],
    }
    add_face = urllib.request.Request(
        'https://japaneast.api.cognitive.microsoft.com/face/v1.0/persongroups/'+PERSON_GROUP_ID+'/persons/'+person['personId']+'/persistedFaces',
        method='POST',
        data=json.dumps(obj).encode("utf-8"),
        headers=headers
    )
    with urllib.request.urlopen(add_face) as response:
        response_body = response.read().decode("utf-8")
        print(response_body)

    # PersonGroupの学習を開始
    train = urllib.request.Request(
        'https://japaneast.api.cognitive.microsoft.com/face/v1.0/persongroups/'+PERSON_GROUP_ID+'/train',
        method='POST',
        data='{}'.encode("utf-8"),
        headers=headers
    )
    with urllib.request.urlopen(train) as response:
        response_body = response.read().decode("utf-8")
        print(response_body)

    return 'メンバーを登録しました。'

# PersonGroupが存在するかのチェック
def is_exists_person_group():
    headers = {
        'Ocp-Apim-Subscription-Key': FACE_API_SUBSCRIPTION_KEY
    }
    get_person_group = urllib.request.Request(
        'https://japaneast.api.cognitive.microsoft.com/face/v1.0/persongroups/'+PERSON_GROUP_ID,
        headers=headers
    )
    try:
        urllib.request.urlopen(get_person_group)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        else:
            raise

# ファイルをスクリプトとして実行した際に
# ホスト0.0.0.0, ポート3001番でサーバーを起動
if __name__ == '__main__':
    api.run(host='0.0.0.0', port=3001)