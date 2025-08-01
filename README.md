## AI
## ✨ 작업 내용
    - 프로필 기반 자소서를 작성하기 위한 사전 단계 및 자소서 작성하는 코드입니다. 프로필 작성 단계를 'profilequestioning.py'로, 그 프로필을 기반으로 작성한 자소서는 'personalstatement.py'로 저장했습니다.

    < BASE >
    profile = {
      "basicInfo" : {
          "name" : None,
          "age" : None,
          "gender" : None,
          "email" : None,
          "phone" : None
      },
  
      "personalNarratives" : {
          "personality" : None,
          "values" : None,
          "problemSolvingExperience" : None
      }
    }
    와 같이 dictionary 형태로 사용자의 정보를 기입합니다
    
    < profilequestioning.py >
    - 몇 가지의 질의응답을 통해 profile 속의 item을 채워넣습니다. 이때, 그 item이 basicInfo가 아닌 field에서의 item, 곧 사용자가 기입한 응답이 15자 내외(임시기준)로 나올 시, 추가 질문을 3개(임시기준)만든 뒤, 사용자의 응답을 기다리며 답변을 보완합니다.

    < personalstatement.py >
    - 위 과정으로 작성된 profile dictionary 중 personalNarratives 와 basicInfo에서 name과 age를 가져와 임의의 template 기준에 맞게 1500자의 자소서를 생성합니다.
    ---
        
## 📝 적용 범위
    - ?
        
    ---
        
## 📌 참고 사항
    - Template 은 계속 수정해야하는 사항입니다. 두 코드 속의 template 은 임의로만 판단하여 주십시오.
    - 이해의 편의성을 위해 사용자의 '프로필 입력' 단계와 '자소서 작성' 단계를 분리해서 먼저 올립니다.
    - 단, 두 코드는 profile 이라는 dictionary 변수를 공통으로 보유하고 있다는 사실을 염두해주십시오.
    - profile 구조도 더 구체화 및 정제될 필요가 있습니다. 혹시 제가 포함시켜야하는데 누락된 것이 있다면 말씀부탁드립니다.
    - (임시기준)이 다소 있습니다. 차차 수정해나가겠습니다.

