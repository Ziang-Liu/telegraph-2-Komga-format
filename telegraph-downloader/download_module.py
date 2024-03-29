import requests, re, os, zipfile, concurrent.futures, time, shutil
from logger import logger
from bs4 import BeautifulSoup
from env import *
from fake_useragent import UserAgent
try:
    import epub
except Exception as e:
    logger.error(f'DOWNLOAD MODULE: Fail to import lxml, error {e}')
    logger.warning('DOWNLOAD MODULE: The Epub function will not work.')
    logger.info('DOWNLOAD MODULE: Try to check files from lxml lib...')
    import importlib.util
    try:
        spec = importlib.util.find_spec('lxml')
        for root, dirs, files in os.walk(spec.submodule_search_locations[0]):
            for file in files:
                logger.info(os.path.join(root, file))
            for dir in dirs:
                logger.info (os.path.join(root, dir))
    except Exception as e:
        logger.info(f'DOWNLOAD MODULE: {e}')
            
# import from env (used by docker)
try:
    download_threads = int(DOWNLOAD_THREADS)
    proxy_url = {'http' : PROXY_URL, 'https' : PROXY_URL}
except (ValueError, TypeError):
    download_threads = 8 # 默认多线程为 8
    proxy_url = None
download_location = DOWNLOAD_PATH

def get_default_folder():
    current_directory = os.path.dirname(__file__)
    new_folder_path = os.path.join(current_directory, "download")
    os.makedirs(new_folder_path, exist_ok=True)
    return new_folder_path

def get_pictures(url, file_path) -> str:
    if not os.path.exists(file_path): # 图片没有下载的情况下写入图片
        requested_url = requests.get(url, proxies=proxy_url)
        with open(file_path, 'wb') as f:
            for chunk in requested_url.iter_content(chunk_size=128):
                f.write(chunk)
    else:
        return

def get_pictures_urls(text) -> str:
    urls = []
    start_tag = 'img src="'  # 图片URL的起始标签
    end_quote = '"'  # 图片URL的结束标签
    start = 0
    while True:
        start = text.find(start_tag, start)  # 查找图片URL的起始位置
        if start == -1:  # 如果找不到起始标签，则结束循环
            break 
        start += len(start_tag)  # 移动到起始标签之后
        end = text.find(end_quote, start)  # 查找图片URL的结束位置
        if end == -1:  # 如果找不到结束标签，则结束循环
            break
        urls.append(text[start:end])  # 将找到的图片URL添加到列表中
        start = end  # 移动到下一个起始位置
    
    return urls

def del_images(path,file_list):
    for image in file_list:  # 删除原始文件夹中除压缩包之外的.jpg
        if ".jpg" in image:
            image_path = os.path.join(path, image)
            os.remove(image_path)

def zip_folder(path, output=None) -> str:
    file_list = os.listdir(path)  # 获取文件夹中的文件列表
    output = output or os.path.basename(path) + '.zip'  # 压缩包的文件名，默认为文件夹名加上.zip后缀
    if os.path.exists(output):  # 如果压缩包已经存在，则返回
        del_images(path,file_list)
        return
    
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as output_zip:
        for root, _, files in os.walk(path):
            relative_root = '' if root == path else root.replace(path, '') + os.sep  # 获取相对路径
            for filename in files:
                if ".jpg" in filename:  # 只压缩.jpg，避免压缩其他类型的文件
                    output_zip.write(os.path.join(root, filename), relative_root + filename)
        output_zip.close()
    del_images(path,file_list)

def extract_number(filename):
    return int(re.search(r'\d+', filename).group())

def create_epub(manga_title, picpath, epubpath) -> str:
    manga = epub.EpubBook()
    
    # 设置标题、标识符和语言
    manga.set_title(manga_title)
    manga.set_identifier('id114514')
    manga.set_language("zh")
    manga.add_author('generated_by_t2kf')

    # 获取图片文件列表并按数字排序
    image_files = [f for f in os.listdir(picpath) if os.path.isfile(os.path.join(picpath, f)) and str(f).endswith(('.jpg'))]
    image_files = sorted(image_files, key=extract_number)  # 根据文件名中的数字排序

    # 将第一张图片作为封面
    if image_files:
        first_image_path = os.path.join(picpath, image_files[0])
        manga.set_cover("cover.jpg", open(first_image_path, "rb").read())

    # 遍历图片文件并添加到电子书中
    for i, image_file in enumerate(image_files):
        image_content = open(os.path.join(picpath, image_file), "rb").read()
        img = epub.EpubImage(
            uid=image_file,
            file_name=image_file,
            media_type="image/jpeg",
            content=image_content,
        )
        manga.add_item(img)

        # 创建包含图片的 HTML 页面并添加到电子书中
        html_content = f"<html><body><img src='{image_file}'></body></html>".encode('utf8')
        html = epub.EpubHtml(title=f"Image {i+1}", file_name=f"image_{i+1}.xhtml", content=html_content)
        manga.add_item(html)
        manga.spine.append(html)  # 将页面添加到书脊
        manga.toc.append(epub.Link(html.file_name, html.title, ''))  # 将页面添加到目录

    # 添加 EpubNav 和 EpubNcx
    manga.add_item(epub.EpubNav())
    manga.add_item(epub.EpubNcx())
    
    os.chdir(epubpath)  # 切换到 EPUB 存储路径
    epub_file_name = manga_title + '.epub'  # 设置 EPUB 文件名
    epub.write_epub(epub_file_name, manga, {})  # 写入 EPUB 文件
    folder_path = os.path.join(epubpath,manga_title)
    shutil.rmtree(folder_path)
    logger.info(f'DOWNLOAD MODULE: EPUB creation complete for: {manga_title}')

def start_download(url=None, address=download_location, isepub=False):
    # 获取用户代理信息
    user_agent = UserAgent()
    ran_user_agent = user_agent.random
    headers = {'User-Agent': ran_user_agent}

    # 检查链接有效性
    if "telegra.ph" not in url:
        logger.warning(f'DOWNLOAD MODULE: Detect wrong link {url}')
        return

    try:
        # 获取图片URL列表
        requested_url = requests.get(url, headers=headers, proxies=proxy_url)
        image_urls = get_pictures_urls(requested_url.text)
        
        # 获取标题
        soup = BeautifulSoup(requested_url.text, 'html.parser')
        manga_title = soup.find("title")
        converted_title = re.sub(
            r'<title>|</title>|\*|\||\?|– Telegraph| |/|:', 
            lambda x: {'<title>': '', '</title>': '', '*': '', '|': '', '?': '', '– Telegraph': '', ' ': '', '/': '∕', ':': '∶'}[x.group()],
            str(manga_title)
        )
    except Exception as e:
        logger.error(f'DOWNLOAD MODULE: {e}, retry in 5 seconds.')
        time.sleep(5)
        start_download(url, address, isepub)

    # 检查路径有效性
    if not os.path.isdir(address):
        logger.error(f'DOWNLOAD MODULE: Invalid path: {address}')
        return

    # 创建目标文件夹
    target_path = os.path.join(address, converted_title)
    os.chdir(address)
    
    if not os.path.exists(target_path):  # 如果路径不存在，则创建新路径
        os.mkdir(target_path)
        logger.info(f'DOWNLOAD MODULE: Create directory: {target_path}')
    else:
        logger.warning('DOWNLOAD MODULE: Directory already exists. Skiping...')

    # 多线程下载图片
    os.chdir(target_path)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=download_threads) as executor:  # 限制并发线程数量
            future_to_url = {executor.submit(get_pictures, 'https://telegra.ph' + url, f'img{i}.jpg'): url for i, url in enumerate(image_urls)}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
    except Exception as e:
        logger.error(f'DOWNLOAD MODULE: {e}, retry in 5 seconds.')
        time.sleep(5)
        start_download(url, address, isepub)

    # 打包下载内容
    if isepub == False:
        zip_folder(target_path)  # 如果不是创建 EPUB，则将内容打包为ZIP文件
        os.chdir(address)
    else:
        try:
            create_epub(converted_title, target_path, address)  # 如果需要创建 EPUB，则调用create_epub函数
            os.chdir(address)
        except Exception as e:
            logger.error(f'DOWNLOAD MODULE: Can not create EPUB, {e}')
            return

    logger.info(f'DOWNLOAD MODULE: Successfully download {converted_title}')
