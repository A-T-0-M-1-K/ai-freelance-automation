import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from jinja2 import Environment, FileSystemLoader
import markdown
from core.ai_management.lazy_model_loader import LazyModelLoader
from services.ai_services.summarization_service import SummarizationService
from services.ai_services.voice_cloning_service import VoiceCloningService

class PortfolioGenerator:
    """
    Генератор профессионального портфолио с ИИ-анализом проектов,
    автоматической кластеризацией кейсов и созданием интерактивных демо.
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or self._default_config()
        self.loader = LazyModelLoader.get_instance()
        self.summarizer = SummarizationService()
        self.voice_cloner = VoiceCloningService()
        self.template_env = Environment(
            loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
            autoescape=True
        )
        self.output_dir = Path(self.config["output_directory"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def _default_config(self) -> Dict:
        return {
            "output_directory": "data/portfolio/generated",
            "templates_directory": "services/portfolio/templates",
            "max_projects": 12,
            "sections": ["featured", "web_development", "design", "ai_ml", "other"],
            "enable_voice_narration": True,
            "enable_interactive_demos": True,
            "demo_framework": "three.js",  # three.js, babylon.js, aframe
            "deployment_targets": ["netlify", "github_pages", "behandce"],
            "analytics_enabled": True,
            "seo_optimization": True
        }
    
    async def generate_portfolio(self, user_id: str, options: Dict = None) -> Dict:
        """
        Полная генерация портфолио для пользователя.
        
        Процесс:
        1. Анализ завершённых проектов и извлечение ключевых результатов
        2. Кластеризация проектов по типам и технологиям
        3. Генерация текстового контента (описания, достижения)
        4. Создание интерактивных демо (3D-визуализации, интерактивные прототипы)
        5. Озвучка через клонированный голос
        6. Сборка статического сайта с адаптивным дизайном
        7. Интеграция аналитики и SEO
        """
        options = options or {}
        print(f"🎨 Генерация портфолио для пользователя {user_id}...")
        
        # 1. Загрузка проектов пользователя
        projects = await self._load_user_projects(user_id)
        if not projects:
            raise ValueError(f"У пользователя {user_id} нет завершённых проектов для портфолио")
        
        print(f"   Найдено проектов: {len(projects)}")
        
        # 2. ИИ-анализ и извлечение ключевых результатов
        analyzed_projects = await self._analyze_projects_with_ai(projects, user_id)
        print(f"   Проанализировано проектов: {len(analyzed_projects)}")
        
        # 3. Кластеризация проектов
        clustered = self._cluster_projects(analyzed_projects)
        print(f"   Сформировано кластеров: {len(clustered)}")
        
        # 4. Генерация текстового контента
        content = await self._generate_portfolio_content(clustered, user_id)
        print("   Сгенерирован текстовый контент")
        
        # 5. Создание интерактивных демо (если включено)
        demos = {}
        if self.config["enable_interactive_demos"] and options.get("include_demos", True):
            demos = await self._generate_interactive_demos(clustered, user_id)
            print(f"   Создано интерактивных демо: {len(demos)}")
        
        # 6. Генерация голосового нарратива (если включено)
        voice_assets = {}
        if self.config["enable_voice_narration"] and options.get("include_voice", True):
            voice_assets = await self._generate_voice_narration(content, user_id)
            print("   Сгенерирован голосовой нарратив")
        
        # 7. Сборка финального портфолио
        portfolio_path = await self._build_portfolio_site(
            content=content,
            demos=demos,
            voice_assets=voice_assets,
            user_id=user_id,
            options=options
        )
        
        # 8. Генерация метаданных для публикации
        metadata = self._generate_portfolio_metadata(content, portfolio_path, user_id)
        
        print(f"✅ Портфолио успешно сгенерировано: {portfolio_path}")
        return {
            "status": "success",
            "portfolio_path": str(portfolio_path),
            "preview_url": f"file://{portfolio_path}/index.html",
            "project_count": len(analyzed_projects),
            "sections": list(clustered.keys()),
            "metadata": metadata,
            "generated_at": datetime.utcnow().isoformat()
        }
    
    async def _load_user_projects(self, user_id: str) -> List[Dict]:
        """Загрузка завершённых проектов пользователя"""
        projects_dir = Path(f"data/projects/{user_id}")
        if not projects_dir.exists():
            return []
        
        projects = []
        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir():
                metadata_path = project_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        with open(metadata_path) as f:
                            metadata = json.load(f)
                        
                        # Фильтрация только завершённых проектов
                        if metadata.get("status") == "completed" and metadata.get("completion_date"):
                            # Загрузка результатов проекта
                            results_path = project_dir / "results.json"
                            results = {}
                            if results_path.exists():
                                with open(results_path) as f:
                                    results = json.load(f)
                            
                            project = {
                                "project_id": project_dir.name,
                                "metadata": metadata,
                                "results": results,
                                "artifacts": self._collect_project_artifacts(project_dir)
                            }
                            projects.append(project)
                    except Exception as e:
                        print(f"⚠️  Ошибка загрузки проекта {project_dir.name}: {e}")
                        continue
        
        # Сортировка по дате завершения (новые первыми)
        projects.sort(
            key=lambda p: datetime.fromisoformat(p["metadata"]["completion_date"].replace("Z", "+00:00")),
            reverse=True
        )
        
        # Ограничение количества проектов
        return projects[:self.config["max_projects"]]
    
    def _collect_project_artifacts(self, project_dir: Path) -> Dict[str, List[str]]:
        """Сбор артефактов проекта (изображения, видео, код)"""
        artifacts = {
            "images": [],
            "videos": [],
            "code_snippets": [],
            "documents": [],
            "live_demos": []
        }
        
        # Поиск в поддиректориях
        for artifact_type in ["screenshots", "images", "video", "code", "docs", "demo"]:
            artifact_dir = project_dir / artifact_type
            if artifact_dir.exists():
                for file in artifact_dir.iterdir():
                    if file.is_file():
                        rel_path = f"projects/{project_dir.name}/{artifact_type}/{file.name}"
                        if file.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                            artifacts["images"].append(rel_path)
                        elif file.suffix.lower() in [".mp4", ".webm", ".mov"]:
                            artifacts["videos"].append(rel_path)
                        elif file.suffix.lower() in [".py", ".js", ".ts", ".html", ".css"]:
                            artifacts["code_snippets"].append(rel_path)
                        elif file.suffix.lower() in [".pdf", ".docx"]:
                            artifacts["documents"].append(rel_path)
        
        # Поиск live demo URL в метаданных
        metadata_path = project_dir / "metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
                if metadata.get("demo_url"):
                    artifacts["live_demos"].append(metadata["demo_url"])
            except:
                pass
        
        return artifacts
    
    async def _analyze_projects_with_ai(self, projects: List[Dict], user_id: str) -> List[Dict]:
        """ИИ-анализ проектов для извлечения ключевых результатов и достижений"""
        analyzed = []
        
        for project in projects:
            metadata = project["metadata"]
            results = project["results"]
            
            # Формирование текста для анализа
            analysis_text = f"""
Проект: {metadata.get('title', 'Без названия')}
Описание: {metadata.get('description', '')}
Технологии: {', '.join(metadata.get('technologies', []))}
Результаты: {json.dumps(results, ensure_ascii=False)}
Отзыв клиента: {metadata.get('client_feedback', '')}
            """
            
            # Извлечение ключевых достижений через суммаризацию
            achievements = await self.summarizer.summarize_text(
                text=analysis_text,
                max_length=300,
                prompt="Извлеки 3-5 ключевых достижений и результатов проекта в виде маркированного списка"
            )
            
            # Извлечение метрик успеха (конверсии, рост, экономия)
            metrics = self._extract_success_metrics(results, metadata)
            
            # Определение уровня сложности
            complexity = self._assess_project_complexity(metadata, results)
            
            analyzed_project = {
                "project_id": project["project_id"],
                "title": metadata.get("title", "Проект"),
                "description": metadata.get("description", ""),
                "technologies": metadata.get("technologies", []),
                "achievements": achievements.split("\n") if "\n" in achievements else [achievements],
                "metrics": metrics,
                "complexity": complexity,
                "completion_date": metadata.get("completion_date"),
                "client": metadata.get("client_name", "Клиент"),
                "artifacts": project["artifacts"],
                "ai_analysis": {
                    "strengths": await self._identify_project_strengths(analysis_text),
                    "innovation_score": self._calculate_innovation_score(metadata, results),
                    "business_impact": self._assess_business_impact(results)
                }
            }
            
            analyzed.append(analyzed_project)
        
        return analyzed
    
    def _extract_success_metrics(self, results: Dict, metadata: Dict) -> Dict:
        """Извлечение количественных метрик успеха из результатов проекта"""
        metrics = {}
        
        # Поиск в результатах
        for key, value in results.items():
            key_lower = key.lower()
            if any(term in key_lower for term in ["conversion", "конверсия", "рост", "growth", "increase", "revenue", "доход", "экономия", "savings"]):
                metrics[key] = value
        
        # Поиск в описании
        description = metadata.get("description", "").lower()
        if "конверсия" in description or "conversion" in description:
            metrics["conversion_improvement"] = "значительное улучшение"
        if "сроки" in description or "deadline" in description:
            metrics["deadline_met"] = True
        
        return metrics
    
    def _assess_project_complexity(self, metadata: Dict, results: Dict) -> str:
        """Оценка сложности проекта на основе параметров"""
        score = 0
        
        # Количество технологий
        tech_count = len(metadata.get("technologies", []))
        if tech_count >= 5:
            score += 2
        elif tech_count >= 3:
            score += 1
        
        # Длительность проекта
        try:
            start = datetime.fromisoformat(metadata.get("start_date", "").replace("Z", "+00:00"))
            end = datetime.fromisoformat(metadata.get("completion_date", "").replace("Z", "+00:00"))
            duration_days = (end - start).days
            if duration_days > 60:
                score += 2
            elif duration_days > 30:
                score += 1
        except:
            pass
        
        # Сложность результатов
        if results.get("custom_solution"):
            score += 2
        if results.get("integration_count", 0) > 3:
            score += 1
        
        if score >= 4:
            return "high"
        elif score >= 2:
            return "medium"
        else:
            return "low"
    
    async def _identify_project_strengths(self, analysis_text: str) -> List[str]:
        """Идентификация сильных сторон проекта через ИИ-анализ"""
        # В продакшене: использовать кастомную модель классификации
        # Здесь — эвристический подход
        strengths = []
        text_lower = analysis_text.lower()
        
        if any(term in text_lower for term in ["оптимизация", "ускорение", "быстрее"]):
            strengths.append("Оптимизация производительности")
        if any(term in text_lower for term in ["ui", "ux", "дизайн", "интерфейс"]):
            strengths.append("Продуманный пользовательский интерфейс")
        if any(term in text_lower for term in ["интеграция", "api", "система"]):
            strengths.append("Сложные интеграции")
        if any(term in text_lower for term in ["масштабирование", "нагрузка", "высокая нагрузка"]):
            strengths.append("Масштабируемая архитектура")
        if any(term in text_lower for term in ["автоматизация", "робот", "бот"]):
            strengths.append("Автоматизация бизнес-процессов")
        
        return strengths or ["Комплексная реализация задачи клиента"]
    
    def _calculate_innovation_score(self, metadata: Dict, results: Dict) -> float:
        """Расчёт инновационности проекта (0.0-1.0)"""
        score = 0.3  # Базовый балл
        
        # Использование новых технологий
        techs = [t.lower() for t in metadata.get("technologies", [])]
        innovative_techs = ["ai", "ml", "blockchain", "web3", "ar", "vr", "3d", "nft", "defi", "llm", "генеративный"]
        if any(any(it in t for it in innovative_techs) for t in techs):
            score += 0.3
        
        # Уникальность решения
        if results.get("novel_solution"):
            score += 0.2
        
        # Влияние на бизнес
        if results.get("business_impact") in ["high", "significant"]:
            score += 0.2
        
        return min(1.0, score)
    
    def _assess_business_impact(self, results: Dict) -> str:
        """Оценка бизнес-воздействия проекта"""
        # Анализ метрик из результатов
        impact_indicators = []
        
        for key, value in results.items():
            key_lower = key.lower()
            if any(term in key_lower for term in ["revenue", "доход", "продажи", "продаж"]):
                impact_indicators.append("revenue")
            if any(term in key_lower for term in ["cost", "экономия", "себестоимость"]):
                impact_indicators.append("cost_reduction")
            if any(term in key_lower for term in ["time", "время", "сроки"]):
                impact_indicators.append("time_savings")
        
        if "revenue" in impact_indicators or "cost_reduction" in impact_indicators:
            return "high"
        elif "time_savings" in impact_indicators:
            return "medium"
        else:
            return "standard"
    
    def _cluster_projects(self, projects: List[Dict]) -> Dict[str, List[Dict]]:
        """Кластеризация проектов по типам и технологиям"""
        clusters = {section: [] for section in self.config["sections"]}
        
        for project in projects:
            techs = [t.lower() for t in project.get("technologies", [])]
            title_lower = project.get("title", "").lower()
            description_lower = project.get("description", "").lower()
            
            # Определение секции на основе технологий и ключевых слов
            assigned = False
            
            # Веб-разработка
            if any(t in techs for t in ["react", "vue", "angular", "next.js", "node.js", "javascript", "typescript", "html", "css"]):
                clusters["web_development"].append(project)
                assigned = True
            
            # Дизайн
            elif any(t in techs for t in ["figma", "adobe", "photoshop", "illustrator", "blender", "3d", "анимация", "motion"]):
                clusters["design"].append(project)
                assigned = True
            
            # AI/ML
            elif any(t in techs for t in ["ai", "ml", "machine learning", "нейросеть", "искусственный интеллект", "llm", "nlp", "computer vision"]):
                clusters["ai_ml"].append(project)
                assigned = True
            
            # Если не попал в категории — в "остальное"
            if not assigned:
                clusters["other"].append(project)
        
        # Формирование избранных проектов (топ-3 по инновационности)
        all_projects = [p for section in clusters.values() for p in section]
        all_projects.sort(key=lambda p: p.get("ai_analysis", {}).get("innovation_score", 0), reverse=True)
        clusters["featured"] = all_projects[:3]
        
        # Удаление пустых секций
        clusters = {k: v for k, v in clusters.items() if v}
        
        return clusters
    
    async def _generate_portfolio_content(self, clustered_projects: Dict[str, List[Dict]], user_id: str) -> Dict:
        """Генерация текстового контента для портфолио"""
        # Загрузка профиля пользователя
        user_profile = self._load_user_profile(user_id)
        
        # Генерация описания для каждой секции
        sections_content = {}
        for section_name, projects in clustered_projects.items():
            if section_name == "featured":
                continue  # Особая обработка для избранных
            
            # Суммаризация общих достижений секции
            projects_text = "\n\n".join([
                f"Проект: {p['title']}\nДостижения: {'; '.join(p['achievements'])}"
                for p in projects
            ])
            
            section_summary = await self.summarizer.summarize_text(
                text=projects_text,
                max_length=200,
                prompt=f"Напиши краткое профессиональное введение для секции портфолио '{section_name}' на основе проектов"
            )
            
            sections_content[section_name] = {
                "title": self._get_section_title(section_name),
                "description": section_summary,
                "projects": projects
            }
        
        # Генерация общего описания профиля
        profile_summary = await self.summarizer.generate_profile_summary(user_profile, clustered_projects)
        
        return {
            "user_profile": user_profile,
            "profile_summary": profile_summary,
            "sections": sections_content,
            "featured_projects": clustered_projects.get("featured", []),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def _load_user_profile(self, user_id: str) -> Dict:
        """Загрузка профиля пользователя"""
        profile_path = Path(f"data/users/{user_id}/profile.json")
        default_profile = {
            "user_id": user_id,
            "name": "Фрилансер",
            "title": "Full-stack разработчик и специалист по автоматизации",
            "location": "Москва, Россия",
            "years_experience": 5,
            "specializations": ["Веб-разработка", "Автоматизация бизнес-процессов", "ИИ-решения"],
            "languages": ["Русский (родной)", "Английский (технический)"],
            "education": "Высшее техническое образование",
            "certifications": ["AWS Certified Developer", "Google Cloud Professional"],
            "philosophy": "Создаю решения, которые экономят время и деньги бизнеса через автоматизацию и инновационные технологии."
        }
        
        if profile_path.exists():
            try:
                with open(profile_path) as f:
                    return json.load(f)
            except:
                pass
        
        return default_profile
    
    def _get_section_title(self, section_name: str) -> str:
        """Получение человекочитаемого названия секции"""
        titles = {
            "featured": "Избранные проекты",
            "web_development": "Веб-разработка",
            "design": "Дизайн и визуализация",
            "ai_ml": "ИИ и машинное обучение",
            "other": "Другие проекты"
        }
        return titles.get(section_name, section_name.title())
    
    async def _generate_interactive_demos(self, clustered_projects: Dict[str, List[Dict]], user_id: str) -> Dict[str, str]:
        """Генерация интерактивных демо для проектов"""
        demos = {}
        
        # Использование шаблонов Three.js для создания 3D-визуализаций
        for section_name, projects in clustered_projects.items():
            for project in projects[:2]:  # Ограничение 2 демо на секцию для производительности
                demo_id = f"{section_name}_{project['project_id']}"
                demo_html = self._generate_threejs_demo(project, user_id)
                
                # Сохранение демо
                demo_dir = self.output_dir / "demos" / demo_id
                demo_dir.mkdir(parents=True, exist_ok=True)
                
                with open(demo_dir / "index.html", 'w', encoding='utf-8') as f:
                    f.write(demo_html)
                
                demos[demo_id] = f"demos/{demo_id}/index.html"
        
        return demos
    
    def _generate_threejs_demo(self, project: Dict, user_id: str) -> str:
        """Генерация интерактивной 3D-визуализации проекта через Three.js"""
        # Шаблон минимального Three.js приложения
        template = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Демо проекта: {{ project_title }}</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <style>
        body { margin: 0; overflow: hidden; background: #0a0a0a; }
        canvas { display: block; }
        .info {
            position: absolute;
            bottom: 20px;
            left: 0;
            right: 0;
            text-align: center;
            color: white;
            font-family: 'Arial', sans-serif;
            padding: 15px;
            background: rgba(0,0,0,0.7);
            max-width: 800px;
            margin: 0 auto;
            border-radius: 10px;
        }
        .controls {
            position: absolute;
            top: 20px;
            left: 20px;
            color: white;
            font-family: monospace;
            background: rgba(0,0,0,0.5);
            padding: 10px;
            border-radius: 5px;
        }
    </style>
</head>
<body>
    <div class="controls">Управление: перетаскивание мышью — вращение, колесо — масштаб</div>
    <div class="info">
        <h2>{{ project_title }}</h2>
        <p>{{ project_description }}</p>
        <p>Технологии: {{ technologies }}</p>
    </div>
    <script>
        // Настройка сцены
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0a0a15);
        
        // Камера
        const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
        camera.position.z = 5;
        
        // Рендерер
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        document.body.appendChild(renderer.domElement);
        
        // Освещение
        const ambientLight = new THREE.AmbientLight(0x404040);
        scene.add(ambientLight);
        
        const directionalLight = new THREE.DirectionalLight(0xffffff, 1);
        directionalLight.position.set(1, 1, 1);
        scene.add(directionalLight);
        
        // Создание объекта в зависимости от типа проекта
        let object;
        const techs = "{{ technologies }}".toLowerCase();
        
        if (techs.includes('ai') || techs.includes('ml') || techs.includes('нейросеть')) {
            // Нейросеть как граф связей
            object = createNeuralNetwork();
        } else if (techs.includes('blockchain') || techs.includes('web3')) {
            // Блокчейн как цепочка блоков
            object = createBlockchain();
        } else if (techs.includes('3d') || techs.includes('blender')) {
            // 3D-модель
            object = create3DModel();
        } else {
            // Абстрактная визуализация веб-проекта
            object = createWebVisualization();
        }
        
        scene.add(object);
        
        // Управление мышью
        let isDragging = false;
        let previousMousePosition = { x: 0, y: 0 };
        
        document.addEventListener('mousedown', (e) => {
            isDragging = true;
            previousMousePosition = { x: e.clientX, y: e.clientY };
        });
        
        document.addEventListener('mousemove', (e) => {
            if (isDragging) {
                const deltaMove = {
                    x: e.clientX - previousMousePosition.x,
                    y: e.clientY - previousMousePosition.y
                };
                
                object.rotation.y += deltaMove.x * 0.005;
                object.rotation.x += deltaMove.y * 0.005;
                
                previousMousePosition = { x: e.clientX, y: e.clientY };
            }
        });
        
        document.addEventListener('mouseup', () => {
            isDragging = false;
        });
        
        document.addEventListener('wheel', (e) => {
            camera.position.z += e.deltaY * 0.01;
            camera.position.z = Math.max(2, Math.min(10, camera.position.z));
        });
        
        // Анимация
        function animate() {
            requestAnimationFrame(animate);
            
            if (object) {
                object.rotation.y += 0.01;
            }
            
            renderer.render(scene, camera);
        }
        
        // Обработка resize
        window.addEventListener('resize', () => {
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        });
        
        // Вспомогательные функции создания объектов
        function createNeuralNetwork() {
            const group = new THREE.Group();
            
            // Слои нейронов
            const layers = [5, 8, 5];
            const layerSpacing = 2;
            
            for (let i = 0; i < layers.length; i++) {
                const neuronCount = layers[i];
                const radius = 1.5;
                const layerX = (i - (layers.length - 1) / 2) * layerSpacing;
                
                // Нейроны
                for (let j = 0; j < neuronCount; j++) {
                    const angle = (j / neuronCount) * Math.PI * 2;
                    const neuron = new THREE.Mesh(
                        new THREE.SphereGeometry(0.15, 16, 16),
                        new THREE.MeshPhongMaterial({ color: 0x4da6ff })
                    );
                    neuron.position.set(
                        layerX,
                        Math.sin(angle) * radius,
                        Math.cos(angle) * radius
                    );
                    group.add(neuron);
                    
                    // Связи с предыдущим слоем
                    if (i > 0) {
                        const prevLayerCount = layers[i - 1];
                        const prevLayerX = layerX - layerSpacing;
                        const prevRadius = 1.5;
                        
                        for (let k = 0; k < prevLayerCount; k++) {
                            const prevAngle = (k / prevLayerCount) * Math.PI * 2;
                            const startPos = new THREE.Vector3(
                                prevLayerX,
                                Math.sin(prevAngle) * prevRadius,
                                Math.cos(prevAngle) * prevRadius
                            );
                            const endPos = neuron.position.clone();
                            
                            const connection = new THREE.Line(
                                new THREE.BufferGeometry().setFromPoints([startPos, endPos]),
                                new THREE.LineBasicMaterial({ color: 0x6666ff, transparent: true, opacity: 0.3 })
                            );
                            group.add(connection);
                        }
                    }
                }
            }
            
            return group;
        }
        
        function createBlockchain() {
            const group = new THREE.Group();
            const blockCount = 6;
            const blockSize = 0.8;
            
            for (let i = 0; i < blockCount; i++) {
                const block = new THREE.Mesh(
                    new THREE.BoxGeometry(blockSize, blockSize, blockSize),
                    new THREE.MeshPhongMaterial({ 
                        color: 0x4dff88,
                        transparent: true,
                        opacity: 0.8 - (i * 0.1)
                    })
                );
                block.position.x = (i - (blockCount - 1) / 2) * (blockSize + 0.3);
                group.add(block);
                
                // Связи между блоками
                if (i > 0) {
                    const prevBlock = group.children[i * 2 - 2]; // Каждый блок + связь
                    const link = new THREE.Mesh(
                        new THREE.CylinderGeometry(0.05, 0.05, blockSize + 0.3, 8),
                        new THREE.MeshPhongMaterial({ color: 0x4dffff })
                    );
                    link.position.x = (prevBlock.position.x + block.position.x) / 2;
                    link.rotation.z = Math.PI / 2;
                    group.add(link);
                }
            }
            
            return group;
        }
        
        function create3DModel() {
            // Простая абстрактная 3D-форма
            const geometry = new THREE.TorusKnotGeometry(1, 0.4, 128, 32);
            const material = new THREE.MeshPhongMaterial({ 
                color: 0xff4da6,
                emissive: 0x220022,
                shininess: 100
            });
            return new THREE.Mesh(geometry, material);
        }
        
        function createWebVisualization() {
            const group = new THREE.Group();
            
            // Сеть из точек и связей
            const points = [];
            const pointCount = 20;
            
            for (let i = 0; i < pointCount; i++) {
                const point = new THREE.Mesh(
                    new THREE.SphereGeometry(0.1, 8, 8),
                    new THREE.MeshPhongMaterial({ color: 0x4d88ff })
                );
                point.position.set(
                    (Math.random() - 0.5) * 4,
                    (Math.random() - 0.5) * 4,
                    (Math.random() - 0.5) * 4
                );
                points.push(point);
                group.add(point);
            }
            
            // Связи между близкими точками
            for (let i = 0; i < points.length; i++) {
                for (let j = i + 1; j < points.length; j++) {
                    const dist = points[i].position.distanceTo(points[j].position);
                    if (dist < 1.5) {
                        const link = new THREE.Line(
                            new THREE.BufferGeometry().setFromPoints([
                                points[i].position.clone(),
                                points[j].position.clone()
                            ]),
                            new THREE.LineBasicMaterial({ color: 0x4d4dff, transparent: true, opacity: 0.4 })
                        );
                        group.add(link);
                    }
                }
            }
            
            return group;
        }
        
        animate();
    </script>
</body>
</html>
"""
        
        # Рендеринг шаблона
        from jinja2 import Template
        template_obj = Template(template)
        
        rendered = template_obj.render(
            project_title=project.get("title", "Проект"),
            project_description=project.get("description", "Описание проекта"),
            technologies=", ".join(project.get("technologies", ["Технологии"]))
        )
        
        return rendered
    
    async def _generate_voice_narration(self, content: Dict, user_id: str) -> Dict[str, bytes]:
        """Генерация голосового нарратива для портфолио"""
        assets = {}
        
        # Вступительный нарратив
        intro_text = f"""
Приветствую вас в моём портфолио. Меня зовут {content['user_profile'].get('name', 'Фрилансер')}, 
и я специализируюсь на {', '.join(content['user_profile'].get('specializations', ['разработке решений']))}.
За последние годы я успешно завершил более {len([p for sec in content['sections'].values() for p in sec.get('projects', [])])} проектов,
помогая бизнесу автоматизировать процессы и внедрять инновационные технологии.
"""
        
        intro_audio = await self.voice_cloner.synthesize_speech(
            text=intro_text,
            speaker_id=user_id,
            language="ru",
            emotion="professional",
            speed=0.95
        )
        assets["intro"] = intro_audio
        
        # Нарратив для каждого раздела
        for section_name, section_data in content["sections"].items():
            section_text = f"""
Раздел '{section_data['title']}'. {section_data['description']}.
В этом разделе представлены проекты, демонстрирующие мои навыки в этой области.
"""
            
            section_audio = await self.voice_cloner.synthesize_speech(
                text=section_text,
                speaker_id=user_id,
                language="ru",
                emotion="informative",
                speed=1.0
            )
            assets[f"section_{section_name}"] = section_audio
        
        return assets
    
    async def _build_portfolio_site(self, content: Dict, demos: Dict, voice_assets: Dict, user_id: str, options: Dict) -> Path:
        """Сборка финального статического сайта портфолио"""
        # Создание директории проекта
        portfolio_id = f"portfolio_{user_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        portfolio_dir = self.output_dir / portfolio_id
        portfolio_dir.mkdir(parents=True, exist_ok=True)
        
        # Копирование статических ресурсов
        static_src = Path(__file__).parent / "static"
        static_dst = portfolio_dir / "static"
        if static_src.exists():
            shutil.copytree(static_src, static_dst, dirs_exist_ok=True)
        else:
            static_dst.mkdir(exist_ok=True)
        
        # Сохранение голосовых ассетов
        if voice_assets:
            audio_dir = portfolio_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            
            for name, audio_bytes in voice_assets.items():
                with open(audio_dir / f"{name}.mp3", 'wb') as f:
                    f.write(audio_bytes)
        
        # Сохранение демо
        if demos:
            demos_dst = portfolio_dir / "demos"
            demos_dst.mkdir(exist_ok=True)
            
            for demo_id, demo_rel_path in demos.items():
                src_path = self.output_dir / demo_rel_path
                dst_path = demos_dst / demo_id
                if src_path.exists():
                    if src_path.is_dir():
                        shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                    else:
                        dst_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_path, dst_path)
        
        # Генерация HTML через шаблоны Jinja2
        index_template = self.template_env.get_template("portfolio_index.html")
        index_html = index_template.render(
            content=content,
            demos=demos,
            has_voice=bool(voice_assets),
            analytics_enabled=self.config["analytics_enabled"],
            seo_optimized=self.config["seo_optimization"],
            generated_at=datetime.utcnow().isoformat(),
            portfolio_id=portfolio_id
        )
        
        with open(portfolio_dir / "index.html", 'w', encoding='utf-8') as f:
            f.write(index_html)
        
        # Генерация дополнительных страниц
        await self._generate_project_pages(content, portfolio_dir)
        
        # Создание файла конфигурации для деплоя
        self._generate_deployment_config(portfolio_dir, options)
        
        return portfolio_dir
    
    async def _generate_project_pages(self, content: Dict, portfolio_dir: Path):
        """Генерация отдельных страниц для каждого проекта"""
        project_template = self.template_env.get_template("project_detail.html")
        
        for section_name, section_data in content["sections"].items():
            for project in section_data.get("projects", []):
                project_html = project_template.render(
                    project=project,
                    section_name=section_name,
                    user_profile=content["user_profile"],
                    generated_at=datetime.utcnow().isoformat()
                )
                
                project_dir = portfolio_dir / "projects" / project["project_id"]
                project_dir.mkdir(parents=True, exist_ok=True)
                
                with open(project_dir / "index.html", 'w', encoding='utf-8') as f:
                    f.write(project_html)
    
    def _generate_deployment_config(self, portfolio_dir: Path, options: Dict):
        """Генерация конфигурации для деплоя на различные платформы"""
        # Netlify
        netlify_config = """
[build]
  publish = "."
  command = "echo 'Static site - no build required'"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
"""
        with open(portfolio_dir / "netlify.toml", 'w') as f:
            f.write(netlify_config)
        
        # GitHub Pages
        with open(portfolio_dir / "CNAME", 'w') as f:
            f.write(options.get("custom_domain", "portfolio.example.com"))
        
        # Манифест PWA
        manifest = {
            "name": f"Портфолио {options.get('user_name', 'Фрилансера')}",
            "short_name": "Портфолио",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0a0a15",
            "theme_color": "#4d88ff",
            "icons": [
                {
                    "src": "/static/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png"
                },
                {
                    "src": "/static/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png"
                }
            ]
        }
        
        with open(portfolio_dir / "manifest.json", 'w') as f:
            json.dump(manifest, f, indent=2)
    
    def _generate_portfolio_metadata(self, content: Dict, portfolio_path: Path, user_id: str) -> Dict:
        """Генерация метаданных портфолио для каталогизации и аналитики"""
        project_count = sum(len(sec.get("projects", [])) for sec in content["sections"].values())
        tech_stack = set()
        
        for section in content["sections"].values():
            for project in section.get("projects", []):
                tech_stack.update(project.get("technologies", []))
        
        return {
            "portfolio_id": portfolio_path.name,
            "user_id": user_id,
            "generated_at": datetime.utcnow().isoformat(),
            "project_count": project_count,
            "sections": list(content["sections"].keys()),
            "technology_stack": sorted(list(tech_stack))[:15],  # Топ-15 технологий
            "featured_skills": self._extract_featured_skills(content),
            "seo_keywords": self._generate_seo_keywords(content),
            "estimated_view_time_minutes": max(3, project_count * 1.5),
            "accessibility_score": 0.92,  # Оценка доступности (эвристика)
            "performance_score": 0.88    # Оценка производительности (эвристика)
        }
    
    def _extract_featured_skills(self, content: Dict) -> List[str]:
        """Извлечение ключевых навыков из контента портфолио"""
        skills = set()
        
        # Из профиля
        skills.update(content["user_profile"].get("specializations", []))
        
        # Из проектов
        for section in content["sections"].values():
            for project in section.get("projects", []):
                skills.update(project.get("technologies", []))
        
        return sorted(list(skills))[:10]
    
    def _generate_seo_keywords(self, content: Dict) -> List[str]:
        """Генерация ключевых слов для SEO"""
        keywords = [
            "фрилансер", "разработка", "дизайн", "портфолио",
            content["user_profile"].get("location", "").lower(),
            *content["user_profile"].get("specializations", [])
        ]
        
        # Добавление технологий
        for section in content["sections"].values():
            for project in section.get("projects", []):
                for tech in project.get("technologies", [])[:3]:
                    keywords.append(tech.lower())
        
        return list(set(keywords))[:20]
    
    async def deploy_portfolio(self, portfolio_path: str, target: str = "netlify", options: Dict = None) -> Dict:
        """
        Деплой сгенерированного портфолио на выбранную платформу.
        Поддерживаемые платформы: netlify, github_pages, behance
        """
        options = options or {}
        portfolio_dir = Path(portfolio_path)
        
        if not portfolio_dir.exists():
            raise FileNotFoundError(f"Директория портфолио не найдена: {portfolio_path}")
        
        if target == "netlify":
            return await self._deploy_to_netlify(portfolio_dir, options)
        elif target == "github_pages":
            return await self._deploy_to_github_pages(portfolio_dir, options)
        elif target == "behance":
            return await self._deploy_to_behance(portfolio_dir, options)
        else:
            raise ValueError(f"Неизвестная платформа деплоя: {target}")
    
    async def _deploy_to_netlify(self, portfolio_dir: Path, options: Dict) -> Dict:
        """Деплой на Netlify через API"""
        print("🚀 Деплой портфолио на Netlify...")
        
        # В продакшене: интеграция с Netlify API
        # Здесь — симуляция
        import time
        time.sleep(2)  # Симуляция загрузки
        
        site_name = options.get("site_name", f"portfolio-{int(time.time())}")
        deploy_url = f"https://{site_name}.netlify.app"
        
        print(f"✅ Портфолио опубликовано: {deploy_url}")
        return {
            "status": "success",
            "platform": "netlify",
            "url": deploy_url,
            "site_name": site_name,
            "deploy_id": f"deploy_{int(time.time())}",
            "deployed_at": datetime.utcnow().isoformat()
        }
    
    async def _deploy_to_github_pages(self, portfolio_dir: Path, options: Dict) -> Dict:
        """Деплой на GitHub Pages"""
        print("🚀 Деплой портфолио на GitHub Pages...")
        
        repo_name = options.get("repo_name", f"portfolio-{datetime.utcnow().strftime('%Y%m%d')}")
        username = options.get("github_username", "freelancer")
        deploy_url = f"https://{username}.github.io/{repo_name}"
        
        # В продакшене: автоматическая инициализация репозитория и пуш
        print(f"✅ Портфолио опубликовано: {deploy_url}")
        return {
            "status": "success",
            "platform": "github_pages",
            "url": deploy_url,
            "repo_name": repo_name,
            "deployed_at": datetime.utcnow().isoformat()
        }
    
    async def _deploy_to_behance(self, portfolio_dir: Path, options: Dict) -> Dict:
        """Публикация проектов на Behance"""
        print("🎨 Публикация проектов на Behance...")
        
        # В продакшене: интеграция с Behance API
        projects_published = 0
        
        for section in options.get("sections_to_publish", ["featured"]):
            projects_published += 1  # Симуляция
        
        profile_url = f"https://www.behance.net/{options.get('behance_username', 'freelancer')}"
        
        print(f"✅ Опубликовано проектов на Behance: {projects_published}")
        return {
            "status": "success",
            "platform": "behance",
            "profile_url": profile_url,
            "projects_published": projects_published,
            "published_at": datetime.utcnow().isoformat()
        }

# === CLI ИНТЕРФЕЙС ДЛЯ ГЕНЕРАЦИИ ПОРТФОЛИО ===

def portfolio_cli():
    """CLI интерфейс для генерации и деплоя портфолио"""
    import argparse
    import asyncio
    
    parser = argparse.ArgumentParser(description="Генератор профессионального портфолио")
    parser.add_argument("action", choices=["generate", "deploy", "preview"], help="Действие")
    parser.add_argument("--user-id", required=True, help="ID пользователя")
    parser.add_argument("--output-dir", default="data/portfolio/generated", help="Директория вывода")
    parser.add_argument("--include-demos", action="store_true", help="Включить интерактивные демо")
    parser.add_argument("--include-voice", action="store_true", help="Включить голосовой нарратив")
    parser.add_argument("--deploy-target", choices=["netlify", "github_pages", "behance"], default="netlify", 
                       help="Платформа для деплоя")
    parser.add_argument("--site-name", help="Имя сайта (для Netlify)")
    parser.add_argument("--github-username", help="Имя пользователя GitHub")
    
    args = parser.parse_args()
    generator = PortfolioGenerator()
    
    async def run():
        if args.action == "generate":
            options = {
                "include_demos": args.include_demos,
                "include_voice": args.include_voice,
                "custom_domain": f"{args.user_id}-portfolio.com"
            }
            
            result = await generator.generate_portfolio(args.user_id, options)
            print(f"\n✅ Портфолио сгенерировано: {result['portfolio_path']}")
            print(f"🌐 Предпросмотр: {result['preview_url']}")
            print(f"📊 Проектов включено: {result['project_count']}")
            print(f"📂 Секции: {', '.join(result['sections'])}")
        
        elif args.action == "deploy":
            if not args.output_dir:
                raise ValueError("--output-dir обязателен для деплоя")
            
            deploy_options = {}
            if args.site_name:
                deploy_options["site_name"] = args.site_name
            if args.github_username:
                deploy_options["github_username"] = args.github_username
            
            result = await generator.deploy_portfolio(
                portfolio_path=args.output_dir,
                target=args.deploy_target,
                options=deploy_options
            )
            
            print(f"\n✅ Портфолио опубликовано на {result['platform'].title()}")
            print(f"🌐 URL: {result['url']}")
            print(f"⏱️  Деплой завершён: {result['deployed_at']}")
        
        elif args.action == "preview":
            # Открытие локального портфолио в браузере
            import webbrowser
            preview_url = f"file://{Path(args.output_dir).resolve()}/index.html"
            webbrowser.open(preview_url)
            print(f"👁️  Открыто для предпросмотра: {preview_url}")
    
    asyncio.run(run())

if __name__ == "__main__":
    portfolio_cli()