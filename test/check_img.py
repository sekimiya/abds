import requests
from bs4 import BeautifulSoup

url = 'https://www.gundam-ab.com/cardlist/?series=529001'
res = requests.get(url)
soup = BeautifulSoup(res.text, 'html.parser')
imgs = soup.find_all('img', src=True)

for img in imgs:
    src = img['src']
    if 'AB01-001' in src:
        parent = img.parent
        print('--- imgタグの親要素 ---')
        print(parent.prettify())
        print('----------------------') 