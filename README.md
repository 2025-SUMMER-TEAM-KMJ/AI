## AI
## ✨ 작업 내용
    - FastAPI 로 작업한 JSON 수신 작업입니다. 웹의 기능을 설정하는 코드를 'WebSet.py'로, 웹을 여는 코드를 'WebOpen.py'로, JSON을 주고 받는 코드를 'WebTask.py'의 형태로 저장했습니다.

    < WebSet.py >
    - FastAPI 서버를 통해 어떤 역할을 할 것인지를 정의하며, 기능들에 대한 class 정의 및 endpoint 부여를 진행합니다.

    < WebOpen.py >
    - 서버를 엽니다.

    < WebTask.py >
    - 서버를 통해 작업을 합니다. WebOpen으로 연 웹의 url을 기준으로 JSON을 업로드하는 엔드포인트를 더한 url2와 서버로부터 JSON을 받는 엔드포인트를 더한 url3을 정의했습니다. 

    
    ---
        
## 📝 적용 범위
    - 변경된 파일, 디렉터리, 모듈 등을 명시해주세요.
        
    ---
        
## 📌 참고 사항
    - Libraries that should be pre-install
    **
    pip install FastAPI
    pip install fastapi uvicorn nest-asyncio pyngrok
    **

    - colab 환경에서 작성된 코드입니다. vscode로 작업 시도할 시, 추가 작업이 요구됩니다. (ex. pyngrok 환경)
    - WebTask에서 사용된 url2, url3는 이전 작업으로부터 얻은 url을 기준으로 진행되었습니다. 작업을 새로 시작할 시 변경이 필요합니다.
    - WebSet에서 !nrrok 로 사용된 key는 제가 발급받은 개인 key 입니다. main 으로 branch 변경시 "꼭" 수정해야합니다.
    - 차차 수정해보겠습니다. 오작동 및 제가 인지하지 못한 부분이 있으면 언제든 연락해주십시오.
