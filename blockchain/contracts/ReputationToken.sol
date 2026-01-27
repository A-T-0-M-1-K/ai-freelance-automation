// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/math/SafeCast.sol";

/**
 * @title ReputationToken
 * @dev ERC-20 совместимый токен репутации для AI Freelance Automation System.
 *
 * Особенности:
 * - Токены не передаются напрямую: только через системные вызовы (например, за выполнение заказа).
 * - Репутация = баланс + временные бонусы (stake-based weight).
 * - Администратор (владелец) может корректировать репутацию при доказанном мошенничестве.
 * - Все операции логируются для аудита.
 *
 * Используется для:
 * - Оценки надёжности AI-агентов и клиентов,
 * - Расчёта приоритета в очереди заданий,
 * - Доступа к премиальным функциям платформы.
 */
contract ReputationToken is ERC20, Ownable, ReentrancyGuard {
    using SafeCast for uint256;

    // Маппинг: адрес => последнее время обновления репутации
    mapping(address => uint256) public lastUpdated;

    // Минимальный интервал между ручными изменениями (защита от флуда)
    uint256 public constant MIN_UPDATE_INTERVAL = 1 hours;

    // События для аудита
    event ReputationGranted(address indexed to, uint256 amount, string reason);
    event ReputationRevoked(address indexed from, uint256 amount, string reason);
    event ReputationFrozen(address indexed account, bool frozen);
    event EmergencyOverride(address indexed operator, address indexed target, int256 delta, string reason);

    // Маппинг замороженных аккаунтов (например, при расследовании)
    mapping(address => bool) public frozen;

    /**
     * @dev Конструктор: создаёт токен "ReputationToken" (символ: RPT)
     */
    constructor() ERC20("ReputationToken", "RPT") {}

    /**
     * @dev Запрещаем стандартную передачу токенов — репутация не товар!
     */
    function transfer(address, uint256) public pure override returns (bool) {
        revert("ReputationToken: transfers disabled");
    }

    function transferFrom(address, address, uint256) public pure override returns (bool) {
        revert("ReputationToken: transfers disabled");
    }

    /**
     * @dev Начисляет репутацию системному агенту или клиенту.
     * Только владелец (или будущий DAO) может вызывать.
     * @param to Адрес получателя
     * @param amount Сумма (в wei-эквиваленте репутации)
     * @param reason Причина (для аудита)
     */
    function grantReputation(address to, uint256 amount, string memory reason)
        external
        onlyOwner
        nonReentrant
    {
        if (to == address(0)) revert("Invalid address");
        if (amount == 0) revert("Amount must be > 0");
        if (frozen[to]) revert("Account frozen");

        _mint(to, amount);
        lastUpdated[to] = block.timestamp;
        emit ReputationGranted(to, amount, reason);
    }

    /**
     * @dev Отзывает репутацию (например, за нарушение условий).
     * Только владелец.
     */
    function revokeReputation(address from, uint256 amount, string memory reason)
        external
        onlyOwner
        nonReentrant
    {
        if (from == address(0)) revert("Invalid address");
        if (amount == 0) revert("Amount must be > 0");
        if (balanceOf(from) < amount) revert("Insufficient reputation");
        if (frozen[from]) revert("Account frozen");

        _burn(from, amount);
        lastUpdated[from] = block.timestamp;
        emit ReputationRevoked(from, amount, reason);
    }

    /**
     * @dev Экстренная коррекция репутации (положительная или отрицательная).
     * Используется только в критических случаях (например, баг в AI-агенте).
     */
    function emergencyAdjust(address target, int256 delta, string memory reason)
        external
        onlyOwner
        nonReentrant
    {
        if (target == address(0)) revert("Invalid target");
        if (delta == 0) revert("Delta must be != 0");

        if (delta > 0) {
            _mint(target, uint256(delta));
        } else {
            uint256 burnAmount = uint256(-delta);
            if (balanceOf(target) < burnAmount) revert("Insufficient balance for burn");
            _burn(target, burnAmount);
        }

        lastUpdated[target] = block.timestamp;
        emit EmergencyOverride(msg.sender, target, delta, reason);
    }

    /**
     * @dev Замораживает аккаунт (запрет на изменение репутации).
     * Полезно при расследовании споров.
     */
    function freezeAccount(address account, bool status) external onlyOwner {
        frozen[account] = status;
        emit ReputationFrozen(account, status);
    }

    /**
     * @dev Получает "эффективную репутацию" с учётом времени и стейкинга (в будущем).
     * Сейчас — просто баланс, но архитектура готова к расширению.
     */
    function getEffectiveReputation(address account) external view returns (uint256) {
        return balanceOf(account);
    }

    /**
     * @dev Переопределение _beforeTokenTransfer для добавления защиты.
     */
    function _beforeTokenTransfer(
        address from,
        address to,
        uint256 amount
    ) internal override {
        super._beforeTokenTransfer(from, to, amount);

        // Даже внутренние mint/burn должны учитывать заморозку
        if (from != address(0) && frozen[from]) {
            revert("Sender account frozen");
        }
        if (to != address(0) && frozen[to]) {
            revert("Receiver account frozen");
        }
    }
}