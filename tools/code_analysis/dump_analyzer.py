"""
Автоматический анализ дампов памяти и стек-трейсов для генерации исправлений.
Интеграция с ИИ для предложения патчей на основе знаний из базы знаний.
"""

import json
import re
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import ast
import difflib

from core.learning.knowledge_base import KnowledgeBase
from core.ai_management.ai_model_hub import get_ai_model_hub


class DumpAnalyzer:
    """
    Анализатор дампов с автоматической генерацией рекомендаций по исправлению.
    Использует базу знаний для поиска похожих проблем и их решений.
    """

    def __init__(self, knowledge_base_path: str = "data/knowledge/error_patterns.json"):
        self.knowledge_base = KnowledgeBase(knowledge_base_path)
        self.ai_hub = get_ai_model_hub()
        self.patterns = self._load_error_patterns()

    def _load_error_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Загрузка паттернов ошибок из базы знаний"""
        # Пример структуры паттернов
        return {
            'memory_leak': {
                'keywords': ['MemoryError', 'alloc', 'leak', 'gc', 'garbage'],
                'symptoms': ['растет потребление памяти', 'утечка памяти', 'не освобождаются ресурсы'],
                'solutions': [
                    'Проверить циклические ссылки',
                    'Добавить явный вызов gc.collect()',
                    'Использовать слабые ссылки (weakref)',
                    'Ограничить размер кэшей'
                ]
            },
            'timeout': {
                'keywords': ['Timeout', 'timed out', 'connection timeout', 'socket'],
                'symptoms': ['зависание запросов', 'долгие сетевые операции'],
                'solutions': [
                    'Увеличить таймауты',
                    'Добавить экспоненциальный бэк-офф',
                    'Реализовать асинхронные запросы',
                    'Проверить сетевую доступность'
                ]
            },
            'api_rate_limit': {
                'keywords': ['429', 'rate limit', 'quota', 'too many requests'],
                'symptoms': ['блокировка API', 'ограничение запросов'],
                'solutions': [
                    'Реализовать рейт-лимитер',
                    'Добавить экспоненциальную задержку',
                    'Использовать очередь запросов',
                    'Кэшировать результаты'
                ]
            }
        }

    def analyze_dump(self, dump_path: str, error_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Анализ дампа памяти или лога ошибки с генерацией рекомендаций.

        Args:
            dump_path: Путь к файлу дампа
            error_context: Контекст ошибки из системы обработки ошибок

        Returns:
            Отчет с анализом и рекомендациями
        """
        dump_file = Path(dump_path)

        if not dump_file.exists():
            return {'error': f'Файл дампа не найден: {dump_path}'}

        # Определение типа дампа
        if dump_path.endswith('.json'):
            dump_data = json.loads(dump_file.read_text(encoding='utf-8'))
            dump_type = 'structured'
        elif dump_path.endswith('.log') or dump_path.endswith('.txt'):
            dump_data = dump_file.read_text(encoding='utf-8')
            dump_type = 'text'
        else:
            dump_data = dump_file.read_bytes()
            dump_type = 'binary'

        # Анализ в зависимости от типа
        if dump_type == 'structured':
            analysis = self._analyze_structured_dump(dump_data, error_context)
        elif dump_type == 'text':
            analysis = self._analyze_text_dump(dump_data, error_context)
        else:
            analysis = self._analyze_binary_dump(dump_data, error_context)

        # Поиск похожих проблем в базе знаний
        similar_issues = self._find_similar_issues(analysis.get('error_signature', ''))

        # Генерация ИИ-рекомендаций
        ai_recommendations = self._generate_ai_recommendations(analysis, similar_issues)

        # Формирование финального отчета
        report = {
            'timestamp': datetime.now().isoformat(),
            'dump_path': str(dump_path),
            'dump_type': dump_type,
            'analysis': analysis,
            'similar_issues_found': len(similar_issues),
            'similar_issues': similar_issues[:5],  # Топ-5 похожих проблем
            'ai_recommendations': ai_recommendations,
            'automated_fixes': self._generate_automated_fixes(analysis),
            'severity': analysis.get('severity', 'medium'),
            'estimated_resolution_time': self._estimate_resolution_time(analysis)
        }

        # Сохранение отчета
        report_path = dump_file.parent / f"analysis_{dump_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return report

    def _analyze_structured_dump(self, dump_ Dict[str, Any], error_context: Optional[Dict[str, Any]]

    ) -> Dict[str, Any]:
    """Анализ структурированного дампа (JSON)"""
    analysis = {
        'error_signature': '',
        'severity': 'medium',
        'root_cause_candidates': [],
        'memory_issues': {},
        'resource_issues': {},
        'component_affected': 'unknown'
    }

    # Анализ ошибки из контекста
    if error_context:
        analysis[
            'error_signature'] = f"{error_context.get('exception_type', '')}:{error_context.get('exception_message', '')[:100]}"
        analysis['component_affected'] = error_context.get('component', 'unknown')

    # Анализ памяти
    if 'memory' in dump_data:
        mem = dump_data['memory']
        if mem.get('percent', 0) > 90:
            analysis['severity'] = 'critical'
            analysis['memory_issues']['critical_usage'] = True
            analysis['root_cause_candidates'].append('memory_exhaustion')
        elif mem.get('percent', 0) > 80:
            analysis['severity'] = 'high'
            analysis['memory_issues']['high_usage'] = True
            analysis['root_cause_candidates'].append('memory_pressure')

    # Анализ диска
    if 'disk' in dump_data:
        disk = dump_data['disk']
        if disk.get('percent', 0) > 95:
            analysis['severity'] = 'critical'
            analysis['resource_issues']['disk_full'] = True
            analysis['root_cause_candidates'].append('disk_space_exhaustion')

    # Анализ активных задач
    if 'active_tasks' in dump_data:
        long_running_tasks = [
            task for task in dump_data['active_tasks']
            if self._is_task_stuck(task)
        ]
        if long_running_tasks:
            analysis['root_cause_candidates'].append('stuck_task')
            analysis['resource_issues']['blocked_tasks'] = len(long_running_tasks)

    return analysis


def _analyze_text_dump(self, dump_text: str, error_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Анализ текстового дампа (логи, стек-трейсы)"""
    analysis = {
        'error_signature': '',
        'severity': 'medium',
        'root_cause_candidates': [],
        'error_type': 'unknown',
        'affected_files': [],
        'affected_functions': []
    }

    # Извлечение стек-трейса
    traceback_match = re.search(r'Traceback \(most recent call last\):.*?(?=\n\S|\Z)', dump_text, re.DOTALL)
    if traceback_match:
        tb_text = traceback_match.group(0)
        analysis['error_signature'] = self._extract_error_signature(tb_text)
        analysis['affected_files'] = self._extract_affected_files(tb_text)
        analysis['affected_functions'] = self._extract_affected_functions(tb_text)
        analysis['error_type'] = self._classify_error_type(tb_text)

    # Классификация серьезности по ключевым словам
    if any(kw in dump_text.lower() for kw in ['critical', 'fatal', 'corrupt', 'lost data']):
        analysis['severity'] = 'critical'
    elif any(kw in dump_text.lower() for kw in ['error', 'exception', 'failed']):
        analysis['severity'] = 'high'
    elif any(kw in dump_text.lower() for kw in ['warning', 'warn']):
        analysis['severity'] = 'medium'

    return analysis


def _extract_error_signature(self, tb_text: str) -> str:
    """Извлечение сигнатуры ошибки из стек-трейса"""
    # Извлечение типа и сообщения исключения
    lines = tb_text.strip().split('\n')
    if lines:
        last_line = lines[-1].strip()
        return last_line[:200]  # Первые 200 символов для сигнатуры
    return ''


def _extract_affected_files(self, tb_text: str) -> List[str]:
    """Извлечение затронутых файлов из стек-трейса"""
    # Поиск путей к файлам в стек-трейсе
    file_pattern = r'File "([^"]+)", line \d+'
    return re.findall(file_pattern, tb_text)


def _extract_affected_functions(self, tb_text: str) -> List[str]:
    """Извлечение затронутых функций из стек-трейса"""
    # Поиск имен функций
    func_pattern = r'in (\w+)'
    return re.findall(func_pattern, tb_text)


def _classify_error_type(self, tb_text: str) -> str:
    """Классификация типа ошибки"""
    tb_lower = tb_text.lower()

    if any(kw in tb_lower for kw in ['memory', 'alloc', 'gc']):
        return 'memory'
    elif any(kw in tb_lower for kw in ['timeout', 'timed out']):
        return 'timeout'
    elif any(kw in tb_lower for kw in ['connection', 'network', 'socket']):
        return 'network'
    elif any(kw in tb_lower for kw in ['permission', 'denied', 'access']):
        return 'permission'
    elif any(kw in tb_lower for kw in ['key', 'index', 'attribute']):
        return 'data_structure'
    else:
        return 'unknown'


def _is_task_stuck(self, task: Dict[str, Any]) -> bool:
    """Проверка, застряла ли задача"""
    started_at_str = task.get('started_at')
    if not started_at_str:
        return False

    try:
        started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
        duration = (datetime.now() - started_at).total_seconds()
        return duration > 300  # Задача работает дольше 5 минут
    except:
        return False


def _find_similar_issues(self, error_signature: str) -> List[Dict[str, Any]]:
    """Поиск похожих проблем в базе знаний"""
    if not error_signature:
        return []

    # Поиск по ключевым словам
    keywords = self._extract_keywords(error_signature)
    similar = []

    for pattern_name, pattern in self.patterns.items():
        score = sum(1 for kw in keywords if any(pat_kw in kw.lower() for pat_kw in pattern['keywords']))
        if score > 0:
            similar.append({
                'pattern': pattern_name,
                'match_score': score,
                'solutions': pattern['solutions'],
                'documentation': pattern.get('documentation', '')
            })

    # Сортировка по релевантности
    return sorted(similar, key=lambda x: x['match_score'], reverse=True)


def _extract_keywords(self, text: str) -> List[str]:
    """Извлечение ключевых слов из текста"""
    # Простая токенизация
    words = re.findall(r'\b\w+\b', text.lower())
    # Фильтрация стоп-слов
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with'}
    return [w for w in words if len(w) > 3 and w not in stop_words]


def _generate_ai_recommendations(self, analysis: Dict[str, Any], similar_issues: List[Dict[str, Any]]) -> List[str]:
    """Генерация рекомендаций с помощью ИИ"""
    try:
        # Формирование промпта для ИИ
        prompt = self._build_diagnostic_prompt(analysis, similar_issues)

        # Генерация рекомендаций
        model = self.ai_hub.get_model(task_type='text_generation', language='ru')
        response = model(prompt, max_length=500, temperature=0.3)

        # Парсинг ответа
        recommendations = self._parse_ai_response(response)
        return recommendations

    except Exception as e:
        return [
            f"⚠️ Не удалось сгенерировать ИИ-рекомендации: {e}",
            "Рекомендуется ручной анализ дампа специалистом"
        ]


def _build_diagnostic_prompt(self, analysis: Dict[str, Any], similar_issues: List[Dict[str, Any]]) -> str:
    """Формирование промпта для диагностики"""
    prompt = f"""Ты — эксперт по диагностике и отладке Python-приложений.
Проанализируй следующую информацию о сбое и предложи конкретные шаги для исправления:

ТИП ОШИБКИ: {analysis.get('error_type', 'неизвестно')}
СЕРЬЕЗНОСТЬ: {analysis.get('severity', 'medium')}
ЗАТРОНУТЫЕ КОМПОНЕНТЫ: {', '.join(analysis.get('affected_files', [])[:3]) or 'неизвестно'}

КОНТЕКСТ ПРОБЛЕМЫ:
{json.dumps(analysis, indent=2, ensure_ascii=False)}

ПОХОЖИЕ ПРОБЛЕМЫ В БАЗЕ ЗНАНИЙ:
{json.dumps(similar_issues[:3], indent=2, ensure_ascii=False) if similar_issues else 'Не найдено'}

ПРЕДЛОЖИ:
1. Наиболее вероятную первопричину проблемы
2. Конкретные шаги для диагностики
3. Код исправления (если применимо)
4. Меры по предотвращению в будущем

Ответь структурированно на русском языке."""

    return prompt


def _parse_ai_response(self, response: str) -> List[str]:
    """Парсинг ответа ИИ в список рекомендаций"""
    # Простой парсинг по пунктам
    lines = response.split('\n')
    recommendations = []

    for line in lines:
        line = line.strip()
        if line and (line[0].isdigit() and '.' in line[:3] or line.startswith('-') or line.startswith('*')):
            # Извлечение текста после маркера пункта
            content = re.sub(r'^\d+\.\s*|^\-\s*|^\*\s*', '', line)
            if content:
                recommendations.append(content)

    return recommendations or [response[:300] + '...' if len(response) > 300 else response]


def _generate_automated_fixes(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Генерация автоматизированных исправлений (патчей)"""
    fixes = []

    # Автоматические исправления для известных проблем
    if 'memory_issues' in analysis and analysis['memory_issues'].get('critical_usage'):
        fixes.append({
            'type': 'memory_optimization',
            'description': 'Очистка кэша и сборка мусора',
            'script': 'from core.performance.memory_optimizer import get_memory_optimizer; get_memory_optimizer().clear_caches(); import gc; gc.collect()',
            'auto_apply': True,
            'risk_level': 'low'
        })

    if 'resource_issues' in analysis and analysis['resource_issues'].get('disk_full'):
        fixes.append({
            'type': 'disk_cleanup',
            'description': 'Очистка временных файлов старше 24 часов',
            'script': 'from scripts.maintenance.cleanup_old_data import cleanup_temp_files; cleanup_temp_files(age_hours=24)',
            'auto_apply': True,
            'risk_level': 'low'
        })

    return fixes


def _estimate_resolution_time(self, analysis: Dict[str, Any]) -> str:
    """Оценка времени на устранение проблемы"""
    severity = analysis.get('severity', 'medium')
    root_causes = analysis.get('root_cause_candidates', [])

    if severity == 'critical':
        return '1-4 часа (требуется немедленное вмешательство)'
    elif severity == 'high':
        return '4-8 часов'
    elif 'memory_exhaustion' in root_causes or 'disk_space_exhaustion' in root_causes:
        return '30 минут - 2 часа (автоматическое исправление возможно)'
    else:
        return '2-4 часа'


def generate_patch(self, analysis: Dict[str, Any], file_path: str) -> Optional[str]:
    """
    Генерация патча для исправления кода в указанном файле.

    Returns:
        Строка с патчем в формате diff или None если патч не может быть сгенерирован
    """
    try:
        file = Path(file_path)
        if not file.exists():
            return None

        source_code = file.read_text(encoding='utf-8')

        # Анализ кода AST для поиска проблемных мест
        tree = ast.parse(source_code)
        problematic_nodes = self._find_problematic_nodes(tree, analysis)

        if not problematic_nodes:
            return None

        # Генерация исправленного кода
        fixed_code = self._apply_fixes(source_code, problematic_nodes, analysis)

        # Генерация diff
        diff = difflib.unified_diff(
            source_code.splitlines(keepends=True),
            fixed_code.splitlines(keepends=True),
            fromfile=str(file_path),
            tofile=str(file_path) + '.fixed',
            lineterm=''
        )

        return ''.join(diff)

    except Exception as e:
        return f"# Ошибка генерации патча: {e}"


def _find_problematic_nodes(self, tree: ast.AST, analysis: Dict[str, Any]) -> List[ast.AST]:
    """Поиск проблемных узлов в AST на основе анализа"""
    # Упрощенная реализация - в реальной системе нужен полноценный анализатор
    problematic = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Поиск потенциально проблемных вызовов
            if hasattr(node.func, 'id') and node.func.id in ['open', 'exec', 'eval']:
                problematic.append(node)

    return problematic


def _apply_fixes(self, source_code: str, nodes: List[ast.AST], analysis: Dict[str, Any]) -> str:
    """Применение исправлений к исходному коду"""
    # Упрощенная реализация - возвращает оригинальный код с комментариями
    lines = source_code.split('\n')

    # Добавление комментариев с рекомендациями
    recommendation = analysis.get('ai_recommendations', ['Рекомендация недоступна'])[0]
    lines.insert(0, f'# AI-РЕКОМЕНДАЦИЯ: {recommendation}')
    lines.insert(1, '# Сгенерировано автоматическим анализатором дампов')

    return '\n'.join(lines)


# Утилита командной строки
def main():
    import argparse

    parser = argparse.ArgumentParser(description='Анализатор дампов памяти и ошибок')
    parser.add_argument('dump_path', help='Путь к файлу дампа')
    parser.add_argument('--output', '-o', default=None, help='Путь для сохранения отчета')
    parser.add_argument('--context', '-c', default=None, help='JSON с контекстом ошибки')

    args = parser.parse_args()

    analyzer = DumpAnalyzer()

    error_context = None
    if args.context:
        try:
            import json
            error_context = json.loads(Path(args.context).read_text(encoding='utf-8'))
        except Exception as e:
            print(f"Ошибка загрузки контекста: {e}")

    report = analyzer.analyze_dump(args.dump_path, error_context)

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"Отчет сохранен: {args.output}")
    else:
        import json
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()