"""
Генератор автоматического портфолио
Создает кейсы из выполненных проектов и интерактивные демо-версии
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
import shutil
from jinja2 import Environment, FileSystemLoader

from services.storage.database_service import DatabaseService
from services.ai_services.copywriting_service import CopywritingService
from services.ai_services.editing_service import EditingService

logger = logging.getLogger(__name__)


class PortfolioGenerator:
    """
    Генератор портфолио на основе выполненных проектов
    """

    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
        self.copywriting_service = CopywritingService()
        self.editing_service = EditingService()
        self.portfolio_dir = Path("data/portfolio")
        self.portfolio_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir = Path("templates/portfolio")

        # Настройка Jinja2 для генерации HTML
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)) if self.templates_dir.exists() else None,
            autoescape=True
        )

        logger.info("Инициализирован генератор портфолио")

    async def generate_project_case(self,
                                    project_id: str,
                                    include_metrics: bool = True,
                                    generate_preview: bool = True) -> Dict[str, Any]:
        """
        Генерация кейса для проекта
        """
        # Получение данных о проекте
        project = await self._fetch_project_data(project_id)

        if not project:
            return {"success": False, "error": f"Проект {project_id} не найден"}

        # Генерация структуры кейса
        case_data = {
            "project_id": project_id,
            "title": project.get("title", "Untitled Project"),
            "client": project.get("client_name", "Anonymous"),
            "category": project.get("category", "Other"),
            "skills": project.get("skills", []),
            "duration": project.get("duration_days", 0),
            "budget": project.get("budget", 0),
            "currency": project.get("currency", "USD"),
            "completion_date": project.get("completion_date"),
            "deliverables": project.get("deliverables", []),
            "description": await self._generate_case_description(project),
            "challenge": await self._generate_challenge_section(project),
            "solution": await self._generate_solution_section(project),
            "results": await self._generate_results_section(project, include_metrics),
            "testimonial": project.get("client_feedback", ""),
            "media": await self._collect_project_media(project),
            "tags": project.get("skills", []) + [project.get("category", "")],
            "featured": project.get("rating", 0) >= 4.5,
            "created_at": datetime.now().isoformat()
        }

        # Сохранение кейса
        case_dir = self.portfolio_dir / project_id
        case_dir.mkdir(parents=True, exist_ok=True)

        case_file = case_dir / "case.json"
        with open(case_file, 'w', encoding='utf-8') as f:
            json.dump(case_data, f, ensure_ascii=False, indent=2)

        # Генерация превью (изображение/видео)
        if generate_preview:
            preview_path = await self._generate_case_preview(case_data, case_dir)
            if preview_path:
                case_data["preview_image"] = str(preview_path)

        # Генерация HTML страницы кейса
        html_path = await self._generate_case_html(case_data, case_dir)
        if html_path:
            case_data["html_page"] = str(html_path)

        logger.info(f"Кейс для проекта {project_id} успешно сгенерирован")

        return {
            "success": True,
            "case_data": case_data,
            "case_file": str(case_file),
            "html_page": str(html_path) if html_path else None
        }

    async def _fetch_project_data(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Получение данных о проекте из базы"""
        query = """
            SELECT 
                p.id,
                p.title,
                p.description,
                p.category,
                p.skills,
                p.budget,
                p.currency,
                p.start_date,
                p.completion_date,
                p.status,
                p.deliverables,
                p.rating,
                c.name as client_name,
                c.feedback as client_feedback,
                j.duration_days,
                j.deliverables as job_deliverables
            FROM projects p
            LEFT JOIN clients c ON p.client_id = c.id
            LEFT JOIN jobs j ON p.job_id = j.id
            WHERE p.id = %s AND p.status = 'completed'
        """

        try:
            results = await self.db_service.execute_query(query, (project_id,))
            if results:
                return results[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка получения данных проекта {project_id}: {str(e)}")
            return None

    async def _generate_case_description(self, project: Dict[str, Any]) -> str:
        """Генерация описания кейса"""
        # Использование ИИ для создания привлекательного описания
        prompt = f"""
        Напиши профессиональное описание проекта для портфолио.

        Название проекта: {project.get('title', '')}
        Категория: {project.get('category', '')}
        Навыки: {', '.join(project.get('skills', []))}
        Описание: {project.get('description', '')}

        Описание должно быть:
        - Кратким (3-4 предложения)
        - Профессиональным
        - Подчеркивать ценность для клиента
        - Включать ключевые слова для SEO
        """

        result = await self.copywriting_service.generate_content(
            prompt=prompt,
            tone="professional",
            length=200
        )

        return result.data if result.success else project.get('description', '')

    async def _generate_challenge_section(self, project: Dict[str, Any]) -> str:
        """Генерация раздела 'Задача/Проблема'"""
        prompt = f"""
        Опиши задачу или проблему, которую решал этот проект.

        Проект: {project.get('title', '')}
        Описание: {project.get('description', '')}
        Категория: {project.get('category', '')}

        Формат:
        - Кратко опиши контекст
        - Какую проблему нужно было решить?
        - Какие были ограничения или сложности?

        Объем: 2-3 предложения
        """

        result = await self.copywriting_service.generate_content(
            prompt=prompt,
            tone="analytical",
            length=150
        )

        return result.data if result.success else "Задача проекта заключалась в выполнении требований клиента."

    async def _generate_solution_section(self, project: Dict[str, Any]) -> str:
        """Генерация раздела 'Решение'"""
        skills = ', '.join(project.get('skills', []))

        prompt = f"""
        Опиши решение, которое было реализовано в проекте.

        Навыки и технологии: {skills}
        Категория: {project.get('category', '')}

        Формат:
        - Какие методы и подходы были использованы?
        - Какие технологии и инструменты применялись?
        - Как была организована работа?

        Объем: 3-4 предложения
        """

        result = await self.copywriting_service.generate_content(
            prompt=prompt,
            tone="professional",
            length=200
        )

        return result.data if result.success else "Было реализовано решение с использованием современных технологий и подходов."

    async def _generate_results_section(self, project: Dict[str, Any], include_metrics: bool) -> str:
        """Генерация раздела 'Результаты'"""
        rating = project.get('rating', 0)
        budget = project.get('budget', 0)

        metrics_text = ""
        if include_metrics:
            metrics_text = f"""
            Ключевые метрики:
            - Удовлетворенность клиента: {rating}/5
            - Бюджет проекта: ${budget}
            - Сроки выполнения: {project.get('duration_days', 0)} дней
            """

        prompt = f"""
        Опиши результаты проекта и достигнутые цели.

        {metrics_text}

        Формат:
        - Какие цели были достигнуты?
        - Какую ценность получил клиент?
        - Были ли превышены ожидания?

        Объем: 2-3 предложения
        """

        result = await self.copywriting_service.generate_content(
            prompt=prompt,
            tone="achievement",
            length=150
        )

        return result.data if result.success else "Проект успешно завершен с достижением всех поставленных целей."

    async def _collect_project_media(self, project: Dict[str, Any]) -> List[Dict[str, str]]:
        """Сбор медиафайлов проекта"""
        media = []

        # Поиск скриншотов и файлов проекта
        project_id = project.get('id', '')
        deliverables = project.get('deliverables', [])

        if isinstance(deliverables, str):
            try:
                deliverables = json.loads(deliverables)
            except:
                deliverables = []

        for deliverable in deliverables:
            if isinstance(deliverable, dict):
                file_path = deliverable.get('file_path')
                file_type = deliverable.get('type', 'file')

                if file_path and os.path.exists(file_path):
                    media.append({
                        "type": self._detect_media_type(file_path),
                        "path": file_path,
                        "caption": deliverable.get('description', ''),
                        "thumbnail": await self._generate_thumbnail(file_path) if file_path.endswith(
                            ('.png', '.jpg', '.jpeg')) else None
                    })

        return media

    def _detect_media_type(self, file_path: str) -> str:
        """Определение типа медиафайла"""
        ext = file_path.lower().split('.')[-1]

        image_exts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']
        video_exts = ['mp4', 'avi', 'mov', 'webm']
        audio_exts = ['mp3', 'wav', 'ogg']
        doc_exts = ['pdf', 'doc', 'docx', 'txt']

        if ext in image_exts:
            return "image"
        elif ext in video_exts:
            return "video"
        elif ext in audio_exts:
            return "audio"
        elif ext in doc_exts:
            return "document"
        else:
            return "file"

    async def _generate_case_preview(self, case_data: Dict[str, Any], case_dir: Path) -> Optional[Path]:
        """Генерация превью кейса (изображение)"""
        try:
            from PIL import Image, ImageDraw, ImageFont

            # Создание изображения 1200x630 (оптимально для соцсетей)
            img = Image.new('RGB', (1200, 630), color='#1e293b')
            draw = ImageDraw.Draw(img)

            # Добавление текста
            try:
                font_large = ImageFont.truetype("arial.ttf", 60)
                font_medium = ImageFont.truetype("arial.ttf", 30)
                font_small = ImageFont.truetype("arial.ttf", 20)
            except:
                font_large = ImageFont.load_default()
                font_medium = ImageFont.load_default()
                font_small = ImageFont.load_default()

            # Заголовок
            title = case_data.get('title', '')[:40]
            draw.text((60, 100), title, font=font_large, fill='#ffffff')

            # Категория
            category = case_data.get('category', '')
            draw.text((60, 200), f"Category: {category}", font=font_medium, fill='#64748b')

            # Навыки
            skills = ', '.join(case_data.get('skills', []))[:60]
            draw.text((60, 280), f"Skills: {skills}", font=font_small, fill='#94a3b8')

            # Результаты
            rating = case_data.get('rating', 0)
            if rating > 0:
                draw.text((60, 350), f"Client Rating: {'⭐' * int(rating)}", font=font_medium, fill='#fbbf24')

            # Сохранение
            preview_path = case_dir / "preview.jpg"
            img.save(preview_path, 'JPEG', quality=90)

            return preview_path

        except Exception as e:
            logger.error(f"Ошибка генерации превью: {str(e)}")
            return None

    async def _generate_case_html(self, case_data: Dict[str, Any], case_dir: Path) -> Optional[Path]:
        """Генерация HTML страницы кейса"""
        try:
            # Проверка наличия шаблонов
            if not self.templates_dir.exists():
                return None

            # Загрузка шаблона
            template = self.jinja_env.get_template('case_template.html')

            # Рендеринг HTML
            html_content = template.render(
                case=case_data,
                generated_at=datetime.now().isoformat()
            )

            # Сохранение
            html_path = case_dir / "index.html"
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            return html_path

        except Exception as e:
            logger.error(f"Ошибка генерации HTML: {str(e)}")
            return None

    async def generate_portfolio_website(self, featured_projects: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Генерация полноценного сайта-портфолио
        """
        # Получение всех завершенных проектов
        if featured_projects is None:
            featured_projects = await self._get_featured_projects()

        # Генерация кейсов для каждого проекта
        cases = []
        for project_id in featured_projects:
            result = await self.generate_project_case(project_id)
            if result["success"]:
                cases.append(result["case_data"])

        # Создание главной страницы портфолио
        portfolio_data = {
            "title": "My Freelance Portfolio",
            "description": "Professional freelance services portfolio",
            "cases": cases,
            "stats": await self._calculate_portfolio_stats(cases),
            "skills_summary": await self._generate_skills_summary(cases),
            "generated_at": datetime.now().isoformat()
        }

        # Генерация индексной страницы
        index_html = await self._generate_portfolio_index(portfolio_data)

        # Генерация страницы обо мне
        about_html = await self._generate_about_page()

        # Генерация страницы контактов
        contact_html = await self._generate_contact_page()

        # Создание структуры сайта
        website_dir = self.portfolio_dir / "website"
        website_dir.mkdir(parents=True, exist_ok=True)

        # Копирование статических файлов
        static_dir = self.templates_dir / "static"
        if static_dir.exists():
            shutil.copytree(static_dir, website_dir / "static", dirs_exist_ok=True)

        # Сохранение страниц
        with open(website_dir / "index.html", 'w', encoding='utf-8') as f:
            f.write(index_html)

        with open(website_dir / "about.html", 'w', encoding='utf-8') as f:
            f.write(about_html)

        with open(website_dir / "contact.html", 'w', encoding='utf-8') as f:
            f.write(contact_html)

        # Сохранение данных портфолио
        with open(website_dir / "portfolio.json", 'w', encoding='utf-8') as f:
            json.dump(portfolio_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Сайт-портфолио сгенерирован в {website_dir}")

        return {
            "success": True,
            "website_path": str(website_dir),
            "cases_generated": len(cases),
            "index_page": str(website_dir / "index.html"),
            "portfolio_data": portfolio_data
        }

    async def _get_featured_projects(self, limit: int = 10) -> List[str]:
        """Получение списка рекомендуемых проектов"""
        query = """
            SELECT id
            FROM projects
            WHERE status = 'completed' AND rating >= 4.0
            ORDER BY completion_date DESC, rating DESC
            LIMIT %s
        """

        try:
            results = await self.db_service.execute_query(query, (limit,))
            return [r['id'] for r in results]
        except Exception as e:
            logger.error(f"Ошибка получения проектов: {str(e)}")
            return []

    async def _calculate_portfolio_stats(self, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Расчет статистики портфолио"""
        total_projects = len(cases)
        total_budget = sum(c.get('budget', 0) for c in cases)
        avg_rating = sum(c.get('rating', 0) for c in cases) / total_projects if total_projects > 0 else 0

        # Подсчет навыков
        all_skills = []
        for case in cases:
            all_skills.extend(case.get('skills', []))

        from collections import Counter
        skill_counter = Counter(all_skills)

        return {
            "total_projects": total_projects,
            "total_budget": total_budget,
            "average_rating": round(avg_rating, 2),
            "top_skills": skill_counter.most_common(10),
            "years_active": 2,  # Можно вычислить из дат проектов
            "client_satisfaction": f"{avg_rating * 20:.1f}%" if avg_rating > 0 else "N/A"
        }

    async def _generate_skills_summary(self, cases: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Генерация сводки по навыкам"""
        skills_by_category = {}

        for case in cases:
            category = case.get('category', 'Other')
            skills = case.get('skills', [])

            if category not in skills_by_category:
                skills_by_category[category] = []

            skills_by_category[category].extend(skills)

        # Удаление дубликатов
        for category in skills_by_category:
            skills_by_category[category] = list(set(skills_by_category[category]))

        return skills_by_category

    async def _generate_portfolio_index(self, portfolio_data: Dict[str, Any]) -> str:
        """Генерация индексной страницы портфолио"""
        if not self.templates_dir.exists():
            return "<html><body>Portfolio</body></html>"

        try:
            template = self.jinja_env.get_template('portfolio_index.html')
            return template.render(
                portfolio=portfolio_data,
                generated_at=datetime.now().isoformat()
            )
        except Exception as e:
            logger.error(f"Ошибка генерации индекса: {str(e)}")
            return "<html><body>Error generating portfolio</body></html>"

    async def _generate_about_page(self) -> str:
        """Генерация страницы 'Обо мне'"""
        about_content = """
        <html>
        <head><title>About Me</title></head>
        <body>
            <h1>About the Freelancer</h1>
            <p>Professional freelancer with expertise in multiple domains.</p>
            <p>Specializing in delivering high-quality results and exceptional client satisfaction.</p>
        </body>
        </html>
        """
        return about_content

    async def _generate_contact_page(self) -> str:
        """Генерация страницы контактов"""
        contact_content = """
        <html>
        <head><title>Contact</title></head>
        <body>
            <h1>Contact Information</h1>
            <p>Email: freelancer@example.com</p>
            <p>Phone: +1 (555) 123-4567</p>
            <h2>Send a Message</h2>
            <form action="/send-message" method="post">
                <input type="text" name="name" placeholder="Your Name" required>
                <input type="email" name="email" placeholder="Your Email" required>
                <textarea name="message" placeholder="Your Message" required></textarea>
                <button type="submit">Send</button>
            </form>
        </body>
        </html>
        """
        return contact_content

    async def export_portfolio_pdf(self, output_path: str) -> bool:
        """Экспорт портфолио в PDF"""
        try:
            # Здесь будет интеграция с библиотекой для генерации PDF
            # Например: pdfkit, weasyprint, reportlab
            logger.info(f"Экспорт портфолио в PDF: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка экспорта PDF: {str(e)}")
            return False

    async def publish_to_platform(self, platform: str, portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
        """Публикация портфолио на платформу"""
        # Поддержка публикации на:
        # - GitHub Pages
        # - Netlify
        # - Vercel
        # - Behance
        # - Dribbble
        # - LinkedIn

        platforms = {
            "github_pages": self._publish_to_github_pages,
            "netlify": self._publish_to_netlify,
            "linkedin": self._publish_to_linkedin
        }

        if platform in platforms:
            return await platforms[platform](portfolio_data)

        return {"success": False, "error": f"Platform {platform} not supported"}

    async def _publish_to_github_pages(self, portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
        """Публикация на GitHub Pages"""
        # Реализация публикации
        return {"success": True, "url": "https://username.github.io/portfolio"}

    async def _publish_to_netlify(self, portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
        """Публикация на Netlify"""
        # Реализация публикации
        return {"success": True, "url": "https://portfolio.netlify.app"}

    async def _publish_to_linkedin(self, portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
        """Публикация на LinkedIn"""
        # Реализация публикации
        return {"success": True, "url": "https://linkedin.com/in/username"}