// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/governance/Governor.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorCountingSimple.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorVotes.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorVotesQuorumFraction.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorTimelockControl.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorSettings.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorProposalThreshold.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/utils/math/SafeCast.sol";

/**
 * @title DAOGovernance
 * @dev DAO Governance contract for AI Freelance Automation System.
 * Manages autonomous decisions via token-weighted voting by system stakeholders.
 * Used for:
 * - Approving new freelance platforms
 * - Updating AI model parameters
 * - Distributing revenue shares
 * - Emergency protocol upgrades
 *
 * Security features:
 * - 48-hour timelock for critical actions
 * - Quorum = 20% of total supply
 * - Proposal threshold = 0.5% of total supply
 * - Voting period = 7 days
 */
contract DAOGovernance is
    Governor,
    GovernorSettings,
    GovernorCountingSimple,
    GovernorVotes,
    GovernorVotesQuorumFraction,
    GovernorTimelockControl,
    GovernorProposalThreshold
{
    // Treasury address for revenue distribution
    address public treasury;

    // Token used for governance (e.g., AIFREELANCE token)
    IERC20 public immutable governanceToken;

    /**
     * @dev Initializes the DAO with required parameters.
     * @param _token Address of the ERC20 governance token.
     * @param _timelock Address of the TimelockController.
     * @param _treasury Treasury address for collected fees.
     */
    constructor(
        IERC20 _token,
        TimelockController _timelock,
        address _treasury
    )
        Governor("AI_Freelance_Automation_DAO")
        GovernorSettings(
            1 days,           // votingDelay
            7 days,           // votingPeriod
            0                 // proposalThreshold — overridden by GovernorProposalThreshold
        )
        GovernorVotes(_token)
        GovernorVotesQuorumFraction(20) // 20% quorum
        GovernorTimelockControl(_timelock)
    {
        require(address(_token) != address(0), "DAOGovernance: invalid token");
        require(address(_timelock) != address(0), "DAOGovernance: invalid timelock");
        require(_treasury != address(0), "DAOGovernance: invalid treasury");

        governanceToken = _token;
        treasury = _treasury;

        // Set proposal threshold to 0.5% of total supply
        _updateProposalThreshold((governanceToken.totalSupply() * 5) / 1000);
    }

    /**
     * @dev Returns the minimum amount of tokens required to propose.
     */
    function proposalThreshold() public view override(Governor, GovernorProposalThreshold) returns (uint256) {
        return super.proposalThreshold();
    }

    /**
     * @dev Internal function to update proposal threshold safely.
     */
    function _updateProposalThreshold(uint256 newThreshold) internal {
        _setProposalThreshold(newThreshold);
    }

    /**
     * @dev Allows DAO to distribute revenue to treasury or other addresses.
     * Must be executed via proposal → vote → queue → execute.
     */
    function distributeRevenue(address recipient, uint256 amount) external onlyGovernance {
        require(recipient != address(0), "DAOGovernance: invalid recipient");
        bool sent = governanceToken.transfer(recipient, amount);
        require(sent, "DAOGovernance: transfer failed");
    }

    /**
     * @dev Updates the treasury address (requires DAO vote).
     */
    function updateTreasury(address newTreasury) external onlyGovernance {
        require(newTreasury != address(0), "DAOGovernance: invalid treasury");
        treasury = newTreasury;
    }

    /**
     * @dev Ensures only governance can call protected functions.
     */
    modifier onlyGovernance() {
        require(
            _msgSender() == address(this) ||
            _msgSender() == address(timelock()),
            "DAOGovernance: caller is not governance"
        );
        _;
    }

    /**
     * @dev Required by GovernorTimelockControl.
     */
    function state(uint256 proposalId)
        public
        view
        override(Governor, GovernorTimelockControl)
        returns (ProposalState)
    {
        return super.state(proposalId);
    }

    /**
     * @dev Required by GovernorTimelockControl.
     */
    function propose(
        address[] memory targets,
        uint256[] memory values,
        bytes[] memory calldatas,
        string memory description
    ) public override(Governor, GovernorProposalThreshold) returns (uint256) {
        return super.propose(targets, values, calldatas, description);
    }

    /**
     * @dev Required by GovernorTimelockControl.
     */
    function _execute(
        uint256 proposalId,
        address[] memory targets,
        uint256[] memory values,
        bytes[] memory calldatas,
        bytes32 descriptionHash
    ) internal override(Governor, GovernorTimelockControl) {
        super._execute(proposalId, targets, values, calldatas, descriptionHash);
    }

    /**
     * @dev Cancels a proposal (only possible before execution).
     */
    function _cancel(
        address[] memory targets,
        uint256[] memory values,
        bytes[] memory calldatas,
        bytes32 descriptionHash
    ) internal override(Governor, GovernorTimelockControl) returns (uint256) {
        return super._cancel(targets, values, calldatas, descriptionHash);
    }

    /**
     * @dev Gets the voting power of an account at a given block.
     */
    function _getVotes(
        address account,
        uint256 blockNumber,
        bytes memory
    ) internal view override(Governor, GovernorVotes) returns (uint256) {
        return super._getVotes(account, blockNumber, "");
    }

    /**
     * @dev Fallback to prevent ETH from being stuck.
     */
    receive() external payable {
        // Accept ETH for potential future integrations (e.g., gas refunds)
    }
}