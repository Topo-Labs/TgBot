import random
import math
import os
from typing import Tuple, Dict
import asyncio
from concurrent.futures import ThreadPoolExecutor

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from io import BytesIO

from src.utils.logger import bot_logger


class CaptchaService:
    """图形验证码生成服务"""

    # 验证码图片尺寸
    WIDTH = 200
    HEIGHT = 80

    # 字体大小
    FONT_SIZE = 32

    # 颜色配置
    COLORS = [
        (255, 0, 0),      # 红色
        (0, 128, 0),      # 绿色
        (0, 0, 255),      # 蓝色
        (128, 0, 128),    # 紫色
        (255, 165, 0),    # 橙色
        (0, 128, 128),    # 青色
        (128, 128, 0),    # 橄榄色
    ]

    @staticmethod
    def generate_math_problem() -> Tuple[str, int]:
        """生成数学题目和答案 - 只生成 A op B = ? 格式

        Returns:
            Tuple[str, int]: (题目文本, 正确答案)
        """
        problem_types = [
            "addition",
            "subtraction",
            "multiplication",
            "division"
        ]

        problem_type = random.choice(problem_types)

        if problem_type == "addition":
            a = random.randint(10, 99)
            b = random.randint(10, 99)
            question = f"{a} + {b} = ?"
            answer = a + b

        elif problem_type == "subtraction":
            a = random.randint(50, 99)
            b = random.randint(10, 49)
            question = f"{a} - {b} = ?"
            answer = a - b

        elif problem_type == "multiplication":
            a = random.randint(2, 12)
            b = random.randint(2, 12)
            question = f"{a} × {b} = ?"
            answer = a * b

        elif problem_type == "division":
            # 确保整除
            b = random.randint(2, 12)
            answer = random.randint(2, 20)
            a = b * answer
            question = f"{a} ÷ {b} = ?"

        return question, answer

    @staticmethod
    def _create_font():
        """创建字体对象"""
        if not PIL_AVAILABLE:
            return None

        try:
            # 尝试使用系统字体
            font_paths = [
                "/System/Library/Fonts/Arial.ttf",  # macOS
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
                "arial.ttf",  # Windows
                "/usr/share/fonts/TTF/arial.ttf",  # Some Linux distributions
            ]

            for font_path in font_paths:
                if os.path.exists(font_path):
                    return ImageFont.truetype(font_path, CaptchaService.FONT_SIZE)

            # 如果没有找到字体文件，使用默认字体
            return ImageFont.load_default()

        except Exception:
            return ImageFont.load_default()

    @staticmethod
    def _add_noise_lines(draw: ImageDraw.Draw):
        """添加干扰线条"""
        if not PIL_AVAILABLE:
            return

        for _ in range(random.randint(8, 15)):
            x1 = random.randint(0, CaptchaService.WIDTH)
            y1 = random.randint(0, CaptchaService.HEIGHT)
            x2 = random.randint(0, CaptchaService.WIDTH)
            y2 = random.randint(0, CaptchaService.HEIGHT)

            color = random.choice(CaptchaService.COLORS)
            width = random.randint(1, 3)

            draw.line([(x1, y1), (x2, y2)], fill=color, width=width)

    @staticmethod
    def _add_noise_dots(draw: ImageDraw.Draw):
        """添加干扰点"""
        if not PIL_AVAILABLE:
            return

        for _ in range(random.randint(50, 100)):
            x = random.randint(0, CaptchaService.WIDTH)
            y = random.randint(0, CaptchaService.HEIGHT)
            color = random.choice(CaptchaService.COLORS)
            draw.point([(x, y)], fill=color)

    @staticmethod
    def _draw_distorted_text(draw: ImageDraw.Draw, text: str, font):
        """绘制变形文字"""
        if not PIL_AVAILABLE:
            return

        # 计算文字位置
        text_width = draw.textlength(text, font=font)
        start_x = (CaptchaService.WIDTH - text_width) // 2
        start_y = (CaptchaService.HEIGHT - CaptchaService.FONT_SIZE) // 2

        # 为每个字符添加随机偏移和颜色
        current_x = start_x
        for char in text:
            # 随机偏移
            offset_x = random.randint(-5, 5)
            offset_y = random.randint(-8, 8)

            # 随机颜色
            color = random.choice(CaptchaService.COLORS)

            # 随机旋转角度 (PIL的文字旋转比较复杂，这里用偏移模拟)
            char_x = current_x + offset_x
            char_y = start_y + offset_y

            # 绘制字符
            draw.text((char_x, char_y), char, fill=color, font=font)

            # 计算下一个字符的位置
            char_width = draw.textlength(char, font=font)
            current_x += char_width + random.randint(-3, 8)

    @staticmethod
    def _create_captcha_image(question: str) -> bytes:
        """创建验证码图片

        Args:
            question: 数学题目文本

        Returns:
            bytes: 图片的字节数据
        """
        if not PIL_AVAILABLE:
            bot_logger.warning("PIL not available, cannot create captcha image")
            return b''

        try:
            # 创建图片
            image = Image.new('RGB', (CaptchaService.WIDTH, CaptchaService.HEIGHT), 'white')
            draw = ImageDraw.Draw(image)

            # 创建字体
            font = CaptchaService._create_font()

            # 添加背景噪点
            CaptchaService._add_noise_dots(draw)

            # 绘制变形文字
            CaptchaService._draw_distorted_text(draw, question, font)

            # 添加干扰线
            CaptchaService._add_noise_lines(draw)

            # 转换为字节
            buffer = BytesIO()
            image.save(buffer, format='PNG')
            return buffer.getvalue()

        except Exception as e:
            bot_logger.error(f"Error creating captcha image: {e}")
            # 返回空字节，调用方应该处理这种情况
            return b''

    @staticmethod
    async def generate_captcha() -> Dict:
        """异步生成验证码

        Returns:
            Dict: 包含题目、答案和图片数据的字典
        """
        try:
            # 检查PIL是否可用
            if not PIL_AVAILABLE:
                bot_logger.warning("PIL not available, generating text-only captcha")
                # 生成纯文本验证码
                question, answer = CaptchaService.generate_math_problem()
                return {
                    'question': question,
                    'answer': str(answer),
                    'image_data': b''  # 空图片数据
                }

            # 生成数学题目
            question, answer = CaptchaService.generate_math_problem()

            # 在线程池中生成图片（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                image_data = await loop.run_in_executor(
                    executor,
                    CaptchaService._create_captcha_image,
                    question
                )

            if not image_data:
                bot_logger.warning("Failed to generate captcha image, falling back to text-only")
                return {
                    'question': question,
                    'answer': str(answer),
                    'image_data': b''
                }

            bot_logger.info(f"Generated captcha: {question} = {answer}")

            return {
                'question': question,
                'answer': str(answer),
                'image_data': image_data
            }

        except Exception as e:
            bot_logger.error(f"Error generating captcha: {e}")
            # 返回一个简单的备用验证码
            return {
                'question': "2 + 3 = ?",
                'answer': "5",
                'image_data': b''
            }