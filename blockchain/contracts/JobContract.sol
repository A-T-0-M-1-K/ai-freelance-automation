// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title JobContract
 * @dev Autonomous smart contract for freelance job execution with escrow.
 * Fully compatible with AI_FREELANCE_AUTOMATION system.
 * Supports ETH and any ERC-20 token.
 */
contract JobContract is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    // =============== ENUMS ===============
    enum JobStatus {
        Created,        // Funds deposited, work not started
        InProgress,     // Work in progress
        Completed,      // Work submitted, awaiting approval
        Accepted,       // Client accepted → funds released
        Disputed,       // Dispute initiated
        Cancelled,      // Cancelled by mutual agreement or timeout
        Refunded        // Funds returned to client
    }

    // =============== STRUCTS ===============
    struct Job {
        address client;                 // Who posted the job
        address freelancer;             // AI agent wallet (controlled by system)
        uint256 amount;                 // Total payment amount
        address token;                  // Address(0) = ETH, otherwise ERC-20
        uint256 deadline;               // Unix timestamp
        string deliverableHash;         // IPFS/CID of final work
        JobStatus status;
        bool exists;
    }

    // =============== STORAGE ===============
    uint256 public immutable jobId;
    Job public job;

    // =============== EVENTS ===============
    event JobCreated(uint256 indexed jobId, address client, address freelancer, uint256 amount, address token, uint256 deadline);
    event WorkSubmitted(uint256 indexed jobId, string deliverableHash);
    event JobAccepted(uint256 indexed jobId, address freelancer);
    event JobDisputed(uint256 indexed jobId, string reason);
    event JobCancelled(uint256 indexed jobId);
    event FundsRefunded(uint256 indexed jobId, address client);
    event FundsReleased(uint256 indexed jobId, address freelancer);

    // =============== MODIFIERS ===============
    modifier onlyClient() {
        require(msg.sender == job.client, "JobContract: Only client can call");
        _;
    }

    modifier onlyFreelancer() {
        require(msg.sender == job.freelancer, "JobContract: Only freelancer can call");
        _;
    }

    modifier onlyActive() {
        require(job.status != JobStatus.Accepted &&
                job.status != JobStatus.Cancelled &&
                job.status != JobStatus.Refunded,
                "JobContract: Job is not active");
        _;
    }

    modifier onlyUnstarted() {
        require(job.status == JobStatus.Created, "JobContract: Job already started");
        _;
    }

    // =============== CONSTRUCTOR ===============
    /**
     * @dev Deploys a new job contract.
     * @param _freelancer AI agent wallet address
     * @param _amount Payment amount (in wei or token units)
     * @param _token Token address (address(0) for native ETH)
     * @param _deadline Unix timestamp deadline
     */
    constructor(
        address _freelancer,
        uint256 _amount,
        address _token,
        uint256 _deadline
    ) Ownable(msg.sender) {
        require(_freelancer != address(0), "JobContract: Invalid freelancer");
        require(_amount > 0, "JobContract: Amount must be > 0");
        require(_deadline > block.timestamp, "JobContract: Deadline must be in future");

        jobId = uint256(keccak256(abi.encodePacked(blockhash(block.number - 1), block.timestamp, msg.sender)));

        job = Job({
            client: msg.sender,
            freelancer: _freelancer,
            amount: _amount,
            token: _token,
            deadline: _deadline,
            deliverableHash: "",
            status: JobStatus.Created,
            exists: true
        });

        // Lock funds
        _lockFunds(_amount, _token);

        emit JobCreated(jobId, msg.sender, _freelancer, _amount, _token, _deadline);
    }

    // =============== PUBLIC FUNCTIONS ===============

    /**
     * @dev Freelancer starts work (optional signal)
     */
    function startWork() external onlyFreelancer onlyActive onlyUnstarted {
        job.status = JobStatus.InProgress;
    }

    /**
     * @dev Freelancer submits completed work
     * @param _deliverableHash IPFS hash or content ID of deliverable
     */
    function submitWork(string memory _deliverableHash) external onlyFreelancer onlyActive {
        require(bytes(_deliverableHash).length > 0, "JobContract: Empty deliverable");
        require(job.status == JobStatus.InProgress || job.status == JobStatus.Created,
                "JobContract: Cannot submit from this state");

        job.deliverableHash = _deliverableHash;
        job.status = JobStatus.Completed;

        emit WorkSubmitted(jobId, _deliverableHash);
    }

    /**
     * @dev Client accepts the work → release funds to freelancer
     */
    function acceptWork() external onlyClient onlyActive {
        require(job.status == JobStatus.Completed, "JobContract: Work not submitted");
        _releaseFunds();
        job.status = JobStatus.Accepted;
        emit JobAccepted(jobId, job.freelancer);
    }

    /**
     * @dev Either party can initiate dispute before deadline
     */
    function initiateDispute(string memory _reason) external onlyActive {
        require(msg.sender == job.client || msg.sender == job.freelancer,
                "JobContract: Only parties can dispute");
        require(job.status == JobStatus.Completed, "JobContract: Can only dispute after submission");
        job.status = JobStatus.Disputed;
        emit JobDisputed(jobId, _reason);
        // Note: Resolution handled off-chain or via DAO/oracle in production
    }

    /**
     * @dev Cancel job before work starts (mutual or timeout)
     */
    function cancelJob() external onlyActive {
        require(job.status == JobStatus.Created || job.status == JobStatus.InProgress,
                "JobContract: Cannot cancel now");
        require(block.timestamp > job.deadline ||
                (msg.sender == job.client && job.status == JobStatus.Created) ||
                (msg.sender == job.freelancer && job.status == JobStatus.Created),
                "JobContract: Unauthorized cancellation");

        _refundClient();
        job.status = JobStatus.Cancelled;
        emit JobCancelled(jobId);
    }

    /**
     * @dev Emergency refund if job stuck (e.g., after deadline with no action)
     */
    function requestRefund() external onlyClient {
        require(job.status == JobStatus.Completed || job.status == JobStatus.InProgress,
                "JobContract: Invalid state for refund");
        require(block.timestamp > job.deadline, "JobContract: Deadline not passed");
        _refundClient();
        job.status = JobStatus.Refunded;
        emit FundsRefunded(jobId, job.client);
    }

    // =============== INTERNAL FUNCTIONS ===============
    function _lockFunds(uint256 _amount, address _token) internal {
        if (_token == address(0)) {
            require(msg.value == _amount, "JobContract: ETH amount mismatch");
        } else {
            IERC20(_token).safeTransferFrom(msg.sender, address(this), _amount);
        }
    }

    function _releaseFunds() internal {
        if (job.token == address(0)) {
            payable(job.freelancer).transfer(job.amount);
        } else {
            IERC20(job.token).safeTransfer(job.freelancer, job.amount);
        }
        emit FundsReleased(jobId, job.freelancer);
    }

    function _refundClient() internal {
        if (job.token == address(0)) {
            payable(job.client).transfer(job.amount);
        } else {
            IERC20(job.token).safeTransfer(job.client, job.amount);
        }
    }

    // =============== RECEIVE ETHER ===============
    receive() external payable {
        // Accept ETH only during construction (via _lockFunds)
        revert("JobContract: No direct ETH deposits");
    }
}