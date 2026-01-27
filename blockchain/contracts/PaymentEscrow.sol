// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/math/SafeMath.sol";

/**
 * @title PaymentEscrow
 * @dev Escrow smart contract for freelance automation system.
 * - Client deposits funds (ETH or ERC20).
 * - Freelancer completes work.
 * - Client confirms → funds released to freelancer.
 * - Timeout → auto-refund to client.
 * - Arbiter resolves disputes.
 *
 * Roles:
 * - DEFAULT_ADMIN_ROLE: System owner (can set arbiter)
 * - ARBITER_ROLE: Trusted third party for dispute resolution
 */
contract PaymentEscrow is ReentrancyGuard, AccessControl {
    using SafeMath for uint256;

    // ========== Events ==========
    event Deposit(address indexed client, address indexed freelancer, uint256 amount, bool isERC20, address token);
    event WorkConfirmed(address indexed freelancer, uint256 amount);
    event FundsReleased(address indexed freelancer, uint256 amount);
    event Refunded(address indexed client, uint256 amount);
    event DisputeOpened(address indexed client, address indexed freelancer);
    event DisputeResolved(address indexed winner, uint256 amount);
    event ArbiterChanged(address indexed newArbiter);

    // ========== Roles ==========
    bytes32 public constant ARBITER_ROLE = keccak256("ARBITER_ROLE");

    // ========== Structs ==========
    struct Job {
        address client;
        address freelancer;
        address arbiter;
        uint256 amount;
        address token; // address(0) = ETH, otherwise ERC20
        uint256 deadline;
        bool isCompleted;
        bool isDisputed;
        bool exists;
    }

    // ========== State Variables ==========
    mapping(bytes32 => Job) public jobs; // jobId → Job
    mapping(address => uint256) public balances; // For ETH fallback

    uint256 public constant DEFAULT_TIMEOUT = 7 days; // 7 days to complete job

    // ========== Modifiers ==========
    modifier onlyClient(bytes32 _jobId) {
        require(jobs[_jobId].client == msg.sender, "PaymentEscrow: Only client");
        _;
    }

    modifier onlyFreelancer(bytes32 _jobId) {
        require(jobs[_jobId].freelancer == msg.sender, "PaymentEscrow: Only freelancer");
        _;
    }

    modifier onlyArbiter(bytes32 _jobId) {
        require(jobs[_jobId].arbiter == msg.sender || hasRole(ARBITER_ROLE, msg.sender), "PaymentEscrow: Only arbiter");
        _;
    }

    modifier jobExists(bytes32 _jobId) {
        require(jobs[_jobId].exists, "PaymentEscrow: Job does not exist");
        _;
    }

    // ========== Constructor ==========
    constructor(address _defaultArbiter) {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        if (_defaultArbiter != address(0)) {
            _grantRole(ARBITER_ROLE, _defaultArbiter);
            emit ArbiterChanged(_defaultArbiter);
        }
    }

    // ========== External Functions ==========

    /**
     * @notice Create a new escrow job and deposit funds.
     * @param _freelancer Freelancer address
     * @param _arbiter Arbiter (optional, can be updated later)
     * @param _token Token address (address(0) for ETH)
     * @param _amount Amount to lock
     * @param _customDeadline Custom deadline (0 = use default)
     * @return jobId Unique job identifier
     */
    function createJob(
        address _freelancer,
        address _arbiter,
        address _token,
        uint256 _amount,
        uint256 _customDeadline
    ) external payable nonReentrant returns (bytes32 jobId) {
        require(_freelancer != address(0), "PaymentEscrow: Invalid freelancer");
        require(_amount > 0, "PaymentEscrow: Amount must be > 0");

        jobId = keccak256(abi.encodePacked(msg.sender, _freelancer, block.timestamp, _amount));

        require(!jobs[jobId].exists, "PaymentEscrow: Job ID collision");

        uint256 deadline = _customDeadline > 0 ? _customDeadline : block.timestamp + DEFAULT_TIMEOUT;
        address arbiter = _arbiter != address(0) ? _arbiter : _msgSender();

        jobs[jobId] = Job({
            client: msg.sender,
            freelancer: _freelancer,
            arbiter: arbiter,
            amount: _amount,
            token: _token,
            deadline: deadline,
            isCompleted: false,
            isDisputed: false,
            exists: true
        });

        // Handle payment
        if (_token == address(0)) {
            // ETH
            require(msg.value == _amount, "PaymentEscrow: ETH amount mismatch");
            // ETH remains in contract balance
        } else {
            // ERC20
            IERC20 token = IERC20(_token);
            require(token.transferFrom(msg.sender, address(this), _amount), "PaymentEscrow: ERC20 transfer failed");
        }

        emit Deposit(msg.sender, _freelancer, _amount, _token != address(0), _token);
    }

    /**
     * @notice Freelancer confirms work is done.
     * @param _jobId Job identifier
     */
    function confirmWork(bytes32 _jobId)
        external
        jobExists(_jobId)
        onlyFreelancer(_jobId)
        nonReentrant
    {
        Job storage job = jobs[_jobId];
        require(!job.isCompleted, "PaymentEscrow: Already completed");
        require(!job.isDisputed, "PaymentEscrow: Job is disputed");
        require(block.timestamp <= job.deadline, "PaymentEscrow: Deadline passed");

        job.isCompleted = true;
        emit WorkConfirmed(job.freelancer, job.amount);
    }

    /**
     * @notice Client approves completed work → release funds.
     * @param _jobId Job identifier
     */
    function approveWork(bytes32 _jobId)
        external
        jobExists(_jobId)
        onlyClient(_jobId)
        nonReentrant
    {
        Job storage job = jobs[_jobId];
        require(job.isCompleted, "PaymentEscrow: Work not confirmed");
        require(!job.isDisputed, "PaymentEscrow: Job is disputed");

        _releaseFunds(job);
        delete jobs[_jobId]; // Clean up
    }

    /**
     * @notice Auto-refund if deadline passed and no confirmation.
     * @param _jobId Job identifier
     */
    function refund(bytes32 _jobId)
        external
        jobExists(_jobId)
        nonReentrant
    {
        Job storage job = jobs[_jobId];
        require(block.timestamp > job.deadline, "PaymentEscrow: Deadline not passed");
        require(!job.isCompleted, "PaymentEscrow: Already completed");
        require(!job.isDisputed, "PaymentEscrow: Job is disputed");

        _refundClient(job);
        delete jobs[_jobId];
    }

    /**
     * @notice Open dispute (by client or freelancer).
     * @param _jobId Job identifier
     */
    function openDispute(bytes32 _jobId)
        external
        jobExists(_jobId)
        nonReentrant
    {
        Job storage job = jobs[_jobId];
        require(msg.sender == job.client || msg.sender == job.freelancer, "PaymentEscrow: Not involved");
        require(!job.isDisputed, "PaymentEscrow: Already disputed");
        require(!job.isCompleted || block.timestamp <= job.deadline, "PaymentEscrow: Too late");

        job.isDisputed = true;
        emit DisputeOpened(job.client, job.freelancer);
    }

    /**
     * @notice Arbiter resolves dispute.
     * @param _jobId Job identifier
     * @param _winner Winner address (client or freelancer)
     */
    function resolveDispute(bytes32 _jobId, address _winner)
        external
        jobExists(_jobId)
        onlyArbiter(_jobId)
        nonReentrant
    {
        Job storage job = jobs[_jobId];
        require(job.isDisputed, "PaymentEscrow: No dispute");
        require(_winner == job.client || _winner == job.freelancer, "PaymentEscrow: Invalid winner");

        uint256 amount = job.amount;
        address token = job.token;

        if (token == address(0)) {
            payable(_winner).transfer(amount);
        } else {
            IERC20(token).transfer(_winner, amount);
        }

        emit DisputeResolved(_winner, amount);
        delete jobs[_jobId];
    }

    // ========== Admin Functions ==========

    function setArbiter(address _newArbiter) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(_newArbiter != address(0), "PaymentEscrow: Invalid arbiter");
        _grantRole(ARBITER_ROLE, _newArbiter);
        emit ArbiterChanged(_newArbiter);
    }

    // ========== Internal Helpers ==========

    function _releaseFunds(Job storage job) internal {
        if (job.token == address(0)) {
            payable(job.freelancer).transfer(job.amount);
        } else {
            IERC20(job.token).transfer(job.freelancer, job.amount);
        }
        emit FundsReleased(job.freelancer, job.amount);
    }

    function _refundClient(Job storage job) internal {
        if (job.token == address(0)) {
            payable(job.client).transfer(job.amount);
        } else {
            IERC20(job.token).transfer(job.client, job.amount);
        }
        emit Refunded(job.client, job.amount);
    }

    // ========== Fallback for ETH ==========
    receive() external payable {
        // Accept ETH deposits only via createJob
    }

    fallback() external payable {
        revert("PaymentEscrow: No fallback");
    }
}