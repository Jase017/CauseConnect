import requests
from bs4 import BeautifulSoup
import csv
import re
from tqdm import tqdm
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

def fetch_page_content(url, headers):
    """获取指定 URL 的页面内容"""
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"HTTP 请求错误 ({url}): {e}")
    return None

def find_links(html, base_url):
    """从 HTML 中提取所有链接并返回绝对路径形式的链接列表"""
    soup = BeautifulSoup(html, 'html.parser')
    links = {link.get('href') for link in soup.find_all('a', href=True)}
    full_links = {
        requests.compat.urljoin(base_url, link)
        for link in links
        if not link.startswith("#")  # 跳过锚点链接
    }
    return full_links

def filter_valid_sentence(sentence, min_length=10, max_length=200):
    """检查句子是否有效（长度足够且不过长，并非标题或杂项）"""
    common_invalid_phrases = [
        "learn more", "read more", "current coalitions", "details", "overview", 
        "404", "page not found", "error", "not available"
    ]
    if len(sentence.strip()) < min_length or len(sentence.strip()) > max_length:
        return False
    if any(phrase in sentence.lower() for phrase in common_invalid_phrases):
        return False
    return True

def classify_cause_and_count(sentence, keyword_counter):
    """根据内容分类非营利组织的 'cause' 并统计关键词频率"""
    categories = {
        "environment": ["environment", "climate", "nature", "sustainability", "conservation", "green"],
        "animal": ["animal", "wildlife", "pet", "species", "habitat"],
        "education": ["education", "learning", "teaching", "school", "students", "literacy"],
        "healthcare": ["health", "medicine", "care", "hospital", "disease", "mental health"],
        "poverty": ["poverty", "hunger", "homeless", "basic needs", "food security", "inequality"],
        "human_rights": ["human rights", "justice", "freedom", "equality", "civil rights"],
        "children": ["children", "kids", "youth", "adolescents", "future generation"],
    }
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in sentence.lower():
                keyword_counter[category] += 1

def extract_information(html_content, contacts, mission_sentences, keyword_counter):
    """从 HTML 中提取联系信息和分类的相关语句"""
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text(separator=' ')  # 提取纯文本，并用空格分隔

     # 提取有效邮箱
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    valid_emails = [email for email in emails if not any(char in email for char in ['?', '0', '_'])]
    contacts["emails"].update(valid_emails)

    # 提取有效电话号码
    phone_pattern = r'\b(?:\+?\d{1,3})?[-.\s]?(?:\(?\d{1,4}\)?[-.\s]?)?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b'
    phones = re.findall(phone_pattern, text)
    valid_phones = [phone for phone in phones if re.match(r'\d', phone) and len(phone.replace("-", "").replace(" ", "")) >= 7]
    contacts["phones"].update(valid_phones)

 # 提取包含 “mission” 的句子
    mission_pattern = r'[^.!?]*\bmission\b[^.!?]*[.!?]'
    mission_matches = re.findall(mission_pattern, text, flags=re.I)
    valid_mission_sentences = [
        sentence.strip() for sentence in mission_matches if filter_valid_sentence(sentence)
    ]
    
    # 限制总的 mission_sentences 数量为 3
    for sentence in sorted(valid_mission_sentences, key=len):
        if len(mission_sentences) < 3:  # 控制总数量
            mission_sentences.append(sentence.strip())
        else:
            break

    # 对文本内容进行关键词计数
    for sentence in text.split('.'):
        if filter_valid_sentence(sentence):
            classify_cause_and_count(sentence, keyword_counter)

def get_main_and_secondary_causes(keyword_counter):
    """根据关键词频率确定主要和次要 'cause'"""
    sorted_causes = keyword_counter.most_common()
    main_cause = sorted_causes[0][0] if sorted_causes else "None"
    secondary_cause = sorted_causes[1][0] if len(sorted_causes) > 1 else "None"
    return main_cause, secondary_cause

def scrape_single_page(link, headers, base_url, visited, contacts, mission_sentences, keyword_counter):
    """处理单个页面的爬取和信息提取"""
    if link not in visited and base_url in link:
        visited.add(link)
        page_content = fetch_page_content(link, headers)
        if page_content:
            extract_information(page_content, contacts, mission_sentences, keyword_counter)

def scrape_website(base_url, output_csv):
    """爬取网站主页面及子页面，提取相关信息"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    visited = set()
    contacts = {"emails": set(), "phones": set()}
    mission_sentences = []
    keyword_counter = Counter()
    
    # 获取主页面内容
    main_page_content = fetch_page_content(base_url, headers)
    if not main_page_content:
        print("无法加载主页内容")
        return
    
    visited.add(base_url)
    main_page_links = find_links(main_page_content, base_url)

    # 提取主页面信息
    extract_information(main_page_content, contacts, mission_sentences, keyword_counter)

    # 使用多线程加速爬取子页面
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(scrape_single_page, link, headers, base_url, visited, contacts, mission_sentences, keyword_counter)
            for link in main_page_links
        ]
        for _ in tqdm(futures, desc="Processing Links"):
            pass

    # 获取主要和次要的 cause
    main_cause, secondary_cause = get_main_and_secondary_causes(keyword_counter)

    # 只保存最多3个电话和邮箱
    emails = list(contacts["emails"])[:3]
    phones = list(contacts["phones"])[:3]

    # 保存到 CSV 文件
    with open(output_csv, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Type", "Category", "Content"])
        
        # 写入联系人信息
        for email in emails:
            writer.writerow(["Contact", "Email", email])
        for phone in phones:
            writer.writerow(["Contact", "Phone", phone])
        
        # 写入主要和次要的 cause
        writer.writerow(["Main Cause", main_cause, ""])
        writer.writerow(["Secondary Cause", secondary_cause, ""])
        
        # 写入提取的句子
        for sentence in mission_sentences:
            writer.writerow(["Mission Sentence", "N/A", sentence.strip()])
    
    print(f"数据已成功保存到 {output_csv}")

# 示例调用
if __name__ == "__main__":
    base_url = input("请输入要爬取的网站 URL: ")
    output_csv = "website_information.csv"
    scrape_website(base_url, output_csv)