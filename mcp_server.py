#!/usr/bin/env python3
"""
Wave Accounting MCP Server

This MCP server provides tools to interact with Wave Accounting's GraphQL API.
It supports creating expenses from receipt data, creating income transactions from payment data, 
and managing customers, vendors, and accounts.

Usage:
    python wave_mcp_server.py

Requirements:
    pip install mcp httpx python-dotenv

Environment Variables:
    WAVE_ACCESS_TOKEN: Your Wave API access token (OAuth2 Bearer token)
    WAVE_BUSINESS_ID: Your Wave business ID (optional, will auto-detect if not provided)
"""

import asyncio
import json
import logging
import base64
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
import httpx
import os
from dotenv import load_dotenv
from difflib import SequenceMatcher

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wave-mcp-server")

# Helper method for decoding business id
def decode_business_id(encoded_business_id: str) -> str:
    """
    Decode the base64 encoded business ID and remove the 'Business:' prefix
    
    Args:
        encoded_business_id (str): The base64 encoded business ID
    
    Returns:
        str: The decoded business ID
    """
    try:
        # Decode the base64 string
        decoded = base64.b64decode(encoded_business_id).decode('utf-8')
        
        # Remove the 'Business:' prefix if it exists
        if decoded.startswith('Business:'):
            return decoded[len('Business:'):]
        
        return decoded
    except Exception as e:
        logger.error(f"Failed to decode business ID: {e}")
        return encoded_business_id

class WaveClient:
    """Client for interacting with Wave's GraphQL API"""
    
    # Synonym dictionaries for better category matching
    EXPENSE_SYNONYMS = {
        "food": ["meals", "restaurant", "dining", "eating", "lunch", "dinner", "breakfast"],
        "gas": ["fuel", "gasoline", "petrol", "diesel"],
        "travel": ["transportation", "transport", "trip", "journey"],
        "office": ["supplies", "equipment", "materials", "stationery"],
        "car": ["vehicle", "auto", "automobile", "automotive"],
        "phone": ["mobile", "cellular", "telecommunications", "telecom"],
        "internet": ["web", "online", "broadband", "wifi"],
        "insurance": ["coverage", "policy", "premium"],
        "rent": ["rental", "lease", "leasing"],
        "utilities": ["electric", "electricity", "water", "gas", "power"],
        "marketing": ["advertising", "promotion", "ads"],
        "software": ["subscription", "saas", "app", "application"],
        "training": ["education", "learning", "course", "workshop"],
        "legal": ["attorney", "lawyer", "law", "professional"],
        "accounting": ["bookkeeping", "tax", "financial"],
        "maintenance": ["repair", "service", "upkeep"],
        "entertainment": ["client", "business"]
    }
    
    INCOME_SYNONYMS = {
        "sales": ["revenue", "income", "receipts", "earnings"],
        "consulting": ["services", "professional", "advisory", "expertise"],
        "freelance": ["contract", "project", "gig", "independent"],
        "commission": ["referral", "bonus", "incentive"],
        "interest": ["dividend", "investment", "return"],
        "rental": ["rent", "lease", "property", "real estate", "rental income", "rent income", "property income", "leasing", "tenant"],
        "royalty": ["licensing", "intellectual property", "patent"],
        "other": ["miscellaneous", "misc", "various", "general"]
    }
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = "https://gql.waveapps.com/graphql/public"
        self.business_id = None
        
    async def _make_request(self, query: str, variables: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GraphQL request to Wave API"""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "query": query,
            "variables": variables or {}
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=30.0
            )
            
            # Add detailed error logging
            if response.status_code != 200:
                logger.error(f"API Error: {response.status_code}")
                logger.error(f"Response: {response.text}")
                
            response.raise_for_status()
            return response.json()
    
    async def get_business_info(self, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        """Get information about the user's businesses with pagination"""
        query = """
        query($page: Int!, $pageSize: Int!) {
            businesses(page: $page, pageSize: $pageSize) {
                pageInfo {
                    currentPage
                    totalPages
                    totalCount
                }
                edges {
                    node {
                        id
                        name
                        isPersonal
                        isClassicAccounting
                        isArchived
                    }
                }
            }
        }
        """
        variables = {
            "page": page,
            "pageSize": page_size
        }
        result = await self._make_request(query, variables)
        return result["data"]
    
    async def get_accounts(self, business_id: str) -> List[Dict[str, Any]]:
        """Get chart of accounts for a business with offset-based pagination"""
        all_accounts = []
        page = 1
        page_size = 50
        
        while True:
            query = """
            query($businessId: ID!, $page: Int!, $pageSize: Int!) {
                business(id: $businessId) {
                    id
                    accounts(page: $page, pageSize: $pageSize) {
                        pageInfo {
                            currentPage
                            totalPages
                            totalCount
                        }
                        edges {
                            node {
                                id
                                name
                                displayId
                                type {
                                    name
                                    normalBalanceType
                                }
                                subtype {
                                    name
                                }
                                isArchived
                            }
                        }
                    }
                }
            }
            """
            
            variables = {
                "businessId": business_id,
                "page": page,
                "pageSize": page_size
            }
            
            result = await self._make_request(query, variables)
            accounts_response = result["data"]["business"]["accounts"]
            page_accounts = accounts_response["edges"]
            page_info = accounts_response.get("pageInfo", {})
            
            logger.info(f"API DEBUG: Page {page} - Retrieved {len(page_accounts)} accounts")
            logger.info(f"API DEBUG: Page {page} - Pagination info: {page_info}")
            
            # Add accounts from this page
            all_accounts.extend(page_accounts)
            
            # Check if there are more pages
            current_page = page_info.get("currentPage", page)
            total_pages = page_info.get("totalPages", 1)
            
            if current_page >= total_pages:
                break
                
            page += 1
            
            # Safety check to prevent infinite loops
            if page > 20:
                logger.warning("API DEBUG: Stopped pagination after 20 pages to prevent infinite loop")
                break
        
        logger.info(f"API DEBUG: TOTAL RETRIEVED: {len(all_accounts)} accounts across {page} pages")
        logger.info(f"API DEBUG: Expected total from Wave UI: 7 Income accounts")
        
        # Enhanced debugging with all accounts
        type_counts = {}
        income_accounts = []
        rental_accounts = []
        
        for acc in all_accounts:
            node = acc["node"]
            account_type = node["type"]["name"]
            type_counts[account_type] = type_counts.get(account_type, 0) + 1
            
            if account_type == "Income":
                income_accounts.append(f"'{node['name']}' (archived: {node['isArchived']})")
            
            # Look for rental-related accounts
            name_lower = node["name"].lower()
            if any(term in name_lower for term in ["rental", "rent", "property", "144", "142", "146"]):
                rental_accounts.append(f"'{node['name']}' (type: {node['type']['name']}, archived: {node['isArchived']})")
        
        logger.info(f"API DEBUG: Final account type counts: {type_counts}")
        logger.info(f"API DEBUG: All Income accounts found: {income_accounts}")
        logger.info(f"API DEBUG: All rental-related accounts found: {rental_accounts}")
        
        # Check if we got the expected number of accounts
        income_count = type_counts.get("Income", 0)
        if income_count < 7:
            logger.warning(f"API DEBUG: MISMATCH - Found {income_count} Income accounts but Wave UI shows 7!")
        
        return all_accounts
    
    async def get_vendors(self, business_id: str) -> List[Dict[str, Any]]:
        """Get vendors for a business"""
        query = """
        query($businessId: ID!) {
            business(id: $businessId) {
                id
                vendors {
                    edges {
                        node {
                            id
                            name
                            email
                            isArchived
                        }
                    }
                }
            }
        }
        """
        result = await self._make_request(query, {"businessId": business_id})
        return result["data"]["business"]["vendors"]["edges"]
    
    async def create_vendor(self, business_id: str, name: str, email: Optional[str] = None) -> Dict[str, Any]:
        """Create a new vendor - DISABLED: Wave API doesn't support vendor creation"""
        # Wave's API currently doesn't support vendor creation via GraphQL
        # Users must create vendors manually through Wave's web interface
        return {
            "didSucceed": False,
            "inputErrors": [{"path": "vendor", "message": "Vendor creation not supported via API. Please create vendors manually in Wave's web interface."}],
            "vendor": None
        }
    
    async def create_expense(self, 
                           business_id: str,
                           vendor_id: Optional[str],
                           expense_account_id: str,
                           anchor_account_id: str,
                           amount: str,
                           date: str,
                           description: Optional[str] = None,
                           notes: Optional[str] = None) -> Dict[str, Any]:
        """Create an expense transaction using moneyTransactionCreate"""
        query = """
        mutation($input: MoneyTransactionCreateInput!) {
            moneyTransactionCreate(input: $input) {
                didSucceed
                inputErrors {
                    path
                    message
                    code
                }
                transaction {
                    id
                }
            }
        }
        """
        
        # Convert amount to float for API
        amount_float = float(amount)
        
        variables = {
            "input": {
                "businessId": business_id,
                "externalId": f"receipt-{datetime.now().isoformat()}",
                "date": date,
                "description": description or "Expense from receipt",
                "anchor": {
                    "accountId": anchor_account_id,  # Bank/Credit card account
                    "amount": amount_float,
                    "direction": "WITHDRAWAL"  # Money going out for expense
                },
                "lineItems": [
                    {
                        "accountId": expense_account_id,  # Expense category account
                        "amount": amount_float,
                        "balance": "INCREASE"  # Increasing expenses
                    }
                ]
            }
        }
        
        result = await self._make_request(query, variables)
        return result["data"]["moneyTransactionCreate"]
    
    async def get_anchor_accounts(self, business_id: str) -> List[Dict[str, Any]]:
        """Get accounts that can be used as anchor accounts (bank, credit cards)"""
        accounts = await self.get_accounts(business_id)
        anchor_accounts = [
            acc["node"] for acc in accounts 
            if acc["node"]["type"]["name"] in ["Assets", "Liabilities & Credit Cards"]
            and acc["node"]["subtype"]["name"] in ["Cash & Bank", "Credit Card", "Loan and Line of Credit"]
            and not acc["node"]["isArchived"]
        ]
        return anchor_accounts
    
    async def get_customers(self, business_id: str) -> List[Dict[str, Any]]:
        """Get customers for a business"""
        query = """
        query($businessId: ID!) {
            business(id: $businessId) {
                id
                customers {
                    edges {
                        node {
                            id
                            name
                            email
                            isArchived
                        }
                    }
                }
            }
        }
        """
        result = await self._make_request(query, {"businessId": business_id})
        return result["data"]["business"]["customers"]["edges"]
    
    async def create_income(self, 
                           business_id: str,
                           customer_id: Optional[str],
                           income_account_id: str,
                           anchor_account_id: str,
                           amount: str,
                           date: str,
                           description: Optional[str] = None,
                           notes: Optional[str] = None) -> Dict[str, Any]:
        """Create an income transaction using moneyTransactionCreate"""
        query = """
        mutation($input: MoneyTransactionCreateInput!) {
            moneyTransactionCreate(input: $input) {
                didSucceed
                inputErrors {
                    path
                    message
                    code
                }
                transaction {
                    id
                }
            }
        }
        """
        
        # Convert amount to float for API
        amount_float = float(amount)
        
        # Build line item with optional customer
        line_item = {
            "accountId": income_account_id,  # Income category account
            "amount": amount_float,
            "balance": "INCREASE"  # Increasing income
        }
        
        if customer_id:
            line_item["customerId"] = customer_id
        
        variables = {
            "input": {
                "businessId": business_id,
                "externalId": f"income-{datetime.now().isoformat()}",
                "date": date,
                "description": description or "Income transaction",
                "anchor": {
                    "accountId": anchor_account_id,  # Bank account
                    "amount": amount_float,
                    "direction": "DEPOSIT"  # Money coming in for income
                },
                "lineItems": [line_item]
            }
        }
        
        result = await self._make_request(query, variables)
        return result["data"]["moneyTransactionCreate"]
    
    def find_best_account_match(self, user_category: str, accounts: List[Dict[str, Any]], account_type: str, user_context: Optional[str] = None) -> Tuple[Optional[str], Optional[str], float, str]:
        """
        Find the best matching account for a given category using fuzzy matching and synonyms.
        
        Args:
            user_category: The category name provided by the user
            accounts: List of account objects from Wave API
            account_type: "Expenses" or "Income" to filter account types
            user_context: Additional context (description, payment_description) to extract apartment numbers
            
        Returns:
            Tuple of (account_id, account_name, match_score, explanation)
        """
        if not user_category:
            return None, None, 0.0, "No category provided"
        
        # Debug: Log all accounts to understand the structure
        logger.info(f"DEBUG: Looking for {account_type} accounts. Total accounts received: {len(accounts)}")
        for i, acc in enumerate(accounts[:10]):  # Log first 10 accounts
            node = acc["node"]
            logger.info(f"  Account {i+1}: '{node['name']}' | Type: '{node['type']['name']}' | Subtype: '{node.get('subtype', {}).get('name', 'N/A')}' | Archived: {node['isArchived']}")
        
        # Try multiple filtering strategies
        # Strategy 1: Exact match
        filtered_accounts = [
            acc["node"] for acc in accounts 
            if acc["node"]["type"]["name"] == account_type
            and not acc["node"]["isArchived"]
        ]
        
        # Strategy 2: Case-insensitive match
        if not filtered_accounts:
            filtered_accounts = [
                acc["node"] for acc in accounts 
                if acc["node"]["type"]["name"].lower() == account_type.lower()
                and not acc["node"]["isArchived"]
            ]
        
        # Strategy 3: Income variations
        if not filtered_accounts and account_type == "Income":
            income_variations = ["Income", "INCOME", "Revenue", "REVENUE", "income"]
            filtered_accounts = [
                acc["node"] for acc in accounts 
                if acc["node"]["type"]["name"] in income_variations
                and not acc["node"]["isArchived"]
            ]
        
        # Strategy 4: Check subtypes for income-related terms
        if not filtered_accounts and account_type == "Income":
            income_subtypes = ["INCOME", "REVENUE", "SALES", "OTHER_INCOME"]
            filtered_accounts = [
                acc["node"] for acc in accounts 
                if (acc["node"].get("subtype", {}).get("name", "") in income_subtypes)
                and not acc["node"]["isArchived"]
            ]
        
        logger.info(f"DEBUG: Found {len(filtered_accounts)} {account_type} accounts after filtering")
        
        if not filtered_accounts:
            # Provide helpful error message with debugging guidance
            error_msg = f"No {account_type.lower()} accounts found."
            if account_type == "Income":
                error_msg += " This might explain the rental income matching issue. "
                error_msg += "Try using the 'debug_accounts' tool to see all account types and identify your rental income accounts."
            return None, None, 0.0, error_msg
        
        user_category_lower = user_category.lower().strip()
        best_match = None
        best_score = 0.0
        best_explanation = ""
        
        # Choose appropriate synonym dictionary
        synonyms = self.EXPENSE_SYNONYMS if account_type == "Expenses" else self.INCOME_SYNONYMS
        
        # Extract apartment numbers from user input for apartment-specific matching
        apartment_numbers = []
        all_user_text = f"{user_category} {user_context or ''}"
        
        # Look for apartment/unit numbers (common patterns: 142, 144, 146, "apartment 146", "unit 142")
        import re
        number_patterns = [
            r'\b(14[2-6])\b',  # Specific apartment numbers 142-146
            r'\bapartment\s+(\d+)\b',  # "apartment 123"
            r'\bunit\s+(\d+)\b',       # "unit 123"
            r'\b(\d{3})\b'             # Any 3-digit number
        ]
        
        for pattern in number_patterns:
            matches = re.findall(pattern, all_user_text.lower())
            apartment_numbers.extend(matches)
        
        # Remove duplicates and log
        apartment_numbers = list(set(apartment_numbers))
        if apartment_numbers:
            logger.info(f"APARTMENT DEBUG: Extracted apartment numbers: {apartment_numbers} from '{all_user_text}'")
        
        # Stage 0: Apartment number specific matching (highest priority for rental accounts)
        if apartment_numbers and account_type == "Income":
            for number in apartment_numbers:
                for account in filtered_accounts:
                    account_name_lower = account["name"].lower()
                    # Look for the specific apartment number in account name
                    if number in account_name_lower and "rental" in account_name_lower:
                        return account["id"], account["name"], 0.98, f"Apartment-specific match: Found apartment {number} in '{account['name']}'"
        
        # Stage 1: Exact substring match and prefix matching
        for account in filtered_accounts:
            account_name_lower = account["name"].lower()
            
            # Exact substring match
            if user_category_lower in account_name_lower:
                return account["id"], account["name"], 1.0, f"Exact substring match: '{user_category}' found in '{account['name']}'"
            
            # Prefix matching - account starts with the category (great for "Rental Income - Property A")
            if account_name_lower.startswith(user_category_lower):
                return account["id"], account["name"], 0.95, f"Prefix match: '{account['name']}' starts with '{user_category}'"
            
            # Category starts with account name (e.g., "rent" matches "Rental Income")
            words_in_account = account_name_lower.split()
            if words_in_account and user_category_lower.startswith(words_in_account[0]):
                return account["id"], account["name"], 0.92, f"Category prefix match: '{user_category}' starts with '{words_in_account[0]}' from '{account['name']}'"
        
        # Stage 2: Fuzzy matching with synonyms
        for account in filtered_accounts:
            account_name_lower = account["name"].lower()
            
            # Direct fuzzy match
            similarity = SequenceMatcher(None, user_category_lower, account_name_lower).ratio()
            if similarity > best_score:
                best_match = account
                best_score = similarity
                best_explanation = f"Direct fuzzy match (score: {similarity:.2f})"
            
            # Check each word in account name
            account_words = account_name_lower.split()
            for word in account_words:
                word_similarity = SequenceMatcher(None, user_category_lower, word).ratio()
                if word_similarity > best_score:
                    best_match = account
                    best_score = word_similarity
                    best_explanation = f"Word match: '{user_category}' ~ '{word}' (score: {word_similarity:.2f})"
            
            # Check synonyms
            for key, synonym_list in synonyms.items():
                # Check if user category matches a synonym key
                if user_category_lower == key or user_category_lower in synonym_list:
                    # Look for the key or synonyms in account name
                    if key in account_name_lower:
                        score = 0.9  # High score for synonym match
                        if score > best_score:
                            best_match = account
                            best_score = score
                            best_explanation = f"Synonym match: '{user_category}' relates to '{key}' found in '{account['name']}'"
                    
                    for synonym in synonym_list:
                        if synonym in account_name_lower:
                            score = 0.85  # Slightly lower for indirect synonym
                            if score > best_score:
                                best_match = account
                                best_score = score
                                best_explanation = f"Synonym match: '{user_category}' relates to '{synonym}' found in '{account['name']}'"
                
                # Check if any synonyms match the user input
                if user_category_lower in [key] + synonym_list:
                    for synonym in [key] + synonym_list:
                        if synonym in account_name_lower:
                            score = 0.88
                            if score > best_score:
                                best_match = account
                                best_score = score
                                best_explanation = f"Synonym match: '{user_category}' relates to '{synonym}' in '{account['name']}'"
        
        # Only return matches above threshold
        if best_match and best_score >= 0.6:
            return best_match["id"], best_match["name"], best_score, best_explanation
        
        # Stage 3: Smart fallback strategy
        if filtered_accounts:
            # Return the account with highest score even if below threshold, with explanation
            if best_match and best_score > 0.3:  # Slightly higher threshold for returning low-confidence matches
                explanation = f"Best available match (low confidence): {best_explanation}. Available accounts: {', '.join([acc['name'] for acc in filtered_accounts[:3]])}"
                return best_match["id"], best_match["name"], best_score, explanation
            else:
                # Smart fallback: Look for accounts that contain relevant keywords instead of just using first account
                relevant_account = None
                
                # Look for accounts that contain any relevant terms
                relevant_keywords = []
                for key, synonym_list in synonyms.items():
                    if user_category_lower == key or user_category_lower in synonym_list:
                        relevant_keywords.extend([key] + synonym_list)
                        break
                
                # If we have relevant keywords, look for accounts containing them
                if relevant_keywords:
                    for account in filtered_accounts:
                        account_name_lower = account["name"].lower()
                        for keyword in relevant_keywords:
                            if keyword in account_name_lower:
                                relevant_account = account
                                explanation = f"Fallback match: Found '{keyword}' in '{account['name']}' based on category '{user_category}'. Available accounts: {', '.join([acc['name'] for acc in filtered_accounts[:3]])}"
                                return account["id"], account["name"], 0.5, explanation
                
                # Avoid obviously wrong accounts for rental income
                if user_category_lower in ["rent", "rental", "property"] and len(filtered_accounts) > 1:
                    # Skip accounts that are clearly not rental-related
                    avoid_terms = ["foreign", "exchange", "gain", "loss", "interest", "dividend"]
                    for account in filtered_accounts:
                        account_name_lower = account["name"].lower()
                        if not any(avoid_term in account_name_lower for avoid_term in avoid_terms):
                            explanation = f"Smart fallback: Selected '{account['name']}' (avoided obviously unrelated accounts). Available accounts: {', '.join([acc['name'] for acc in filtered_accounts[:3]])}"
                            return account["id"], account["name"], 0.2, explanation
                
                # Final fallback to first account
                first_account = filtered_accounts[0]
                explanation = f"No good match for '{user_category}'. Using default: '{first_account['name']}'. Available accounts: {', '.join([acc['name'] for acc in filtered_accounts[:3]])}"
                
                # Add warning if only one account available
                if len(filtered_accounts) == 1:
                    explanation += f". ⚠️ WARNING: Only one {account_type.lower()} account found - this suggests account filtering issues. Use 'debug_accounts' tool to investigate."
                
                return first_account["id"], first_account["name"], 0.1, explanation
        
        return None, None, 0.0, f"No {account_type.lower()} accounts available"

# Initialize Wave client
wave_client = None

app = Server("wave-accounting")

@app.list_resources()
async def handle_list_resources() -> list[Resource]:
    """List available resources"""
    return [
        Resource(
            uri="wave://businesses",
            name="Wave Businesses",
            description="Information about your Wave businesses",
            mimeType="application/json",
        ),
        Resource(
            uri="wave://accounts",
            name="Chart of Accounts",
            description="Your business chart of accounts",
            mimeType="application/json",
        ),
        Resource(
            uri="wave://vendors",
            name="Vendors",
            description="Your business vendors",
            mimeType="application/json",
        ),
        Resource(
            uri="wave://customers",
            name="Customers",
            description="Your business customers",
            mimeType="application/json",
        )
    ]

@app.read_resource()
async def handle_read_resource(uri: str) -> str:
    """Read a specific resource"""
    global wave_client
    
    if not wave_client:
        raise RuntimeError("Wave client not initialized")
    
    if uri == "wave://businesses":
        data = await wave_client.get_business_info()
        return json.dumps(data, indent=2)
    
    elif uri == "wave://accounts":
        if not wave_client.business_id:
            raise RuntimeError("Business ID not set")
        accounts = await wave_client.get_accounts(wave_client.business_id)
        return json.dumps(accounts, indent=2)
    
    elif uri == "wave://vendors":
        if not wave_client.business_id:
            raise RuntimeError("Business ID not set")
        vendors = await wave_client.get_vendors(wave_client.business_id)
        return json.dumps(vendors, indent=2)
    
    elif uri == "wave://customers":
        if not wave_client.business_id:
            raise RuntimeError("Business ID not set")
        customers = await wave_client.get_customers(wave_client.business_id)
        return json.dumps(customers, indent=2)
    
    else:
        raise ValueError(f"Unknown resource: {uri}")

@app.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools"""
    return [
        Tool(
            name="create_expense_from_receipt",
            description="Create an expense in Wave from receipt data. Vendor is optional - expenses can be created without vendor association and vendors can be added later.",
            inputSchema={
                "type": "object",
                "properties": {
                    "receipt_text": {
                        "type": "string",
                        "description": "The text content extracted from the receipt"
                    },
                    "vendor_name": {
                        "type": "string",
                        "description": "The name of the vendor/merchant from the receipt (optional)"
                    },
                    "amount": {
                        "type": "string",
                        "description": "The total amount from the receipt (e.g., '25.99')"
                    },
                    "date": {
                        "type": "string",
                        "description": "The date of the transaction (YYYY-MM-DD format)"
                    },
                    "category": {
                        "type": "string",
                        "description": "The expense category (e.g., 'Office Supplies', 'Meals', 'Travel')",
                        "default": "General Expenses"
                    },
                    "description": {
                        "type": "string",
                        "description": "Additional description or notes about the expense"
                    },
                    "payment_account": {
                        "type": "string",
                        "description": "The name of the account to pay from (e.g., 'Cash on hand', 'Business Credit Card'). If not specified, will use the first available account."
                    }
                },
                "required": ["receipt_text", "amount", "date"]
            }
        ),
        Tool(
            name="get_expense_accounts",
            description="Get a list of expense accounts to help categorize receipts",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        ),
        Tool(
            name="search_vendor",
            description="Search for an existing vendor in Wave (vendors must be created manually in Wave's web interface)",
            inputSchema={
                "type": "object",
                "properties": {
                    "vendor_name": {
                        "type": "string",
                        "description": "The name of the vendor to search for"
                    }
                },
                "required": ["vendor_name"]
            }
        ),
        Tool(
            name="set_business",
            description="Set the active business for operations",
            inputSchema={
                "type": "object",
                "properties": {
                    "business_id": {
                        "type": "string",
                        "description": "The Wave business ID to use for operations"
                    }
                },
                "required": ["business_id"]
            }
        ),
        Tool(
            name="list_businesses",
            description="List all available Wave businesses with pagination",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number for pagination (default: 1)",
                        "default": 1,
                        "minimum": 1
                    },
                    "page_size": {
                        "type": "integer", 
                        "description": "Number of businesses per page (default: 10, max: 50)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="create_income_from_payment",
            description="Create an income transaction in Wave from payment/receipt data. Customer is optional - income can be created without customer association and customers can be added later.",
            inputSchema={
                "type": "object",
                "properties": {
                    "payment_description": {
                        "type": "string",
                        "description": "Description of the payment received (e.g., 'Payment for consulting services', 'Invoice #123 payment')"
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "The name of the customer who made the payment (optional)"
                    },
                    "amount": {
                        "type": "string",
                        "description": "The amount received (e.g., '500.00')"
                    },
                    "date": {
                        "type": "string",
                        "description": "The date of the payment (YYYY-MM-DD format)"
                    },
                    "income_category": {
                        "type": "string",
                        "description": "The income category (e.g., 'Sales', 'Service Revenue', 'Consulting Income')",
                        "default": "Sales"
                    },
                    "description": {
                        "type": "string",
                        "description": "Additional description or notes about the income"
                    },
                    "deposit_to_account": {
                        "type": "string",
                        "description": "The name of the bank account to deposit to (e.g., 'Business Checking', 'Savings Account'). If not specified, will use the first available account."
                    }
                },
                "required": ["payment_description", "amount", "date"]
            }
        ),
        Tool(
            name="get_income_accounts",
            description="Get a list of income accounts to help categorize income transactions",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        ),
        Tool(
            name="search_customer",
            description="Search for an existing customer in Wave",
            inputSchema={
                "type": "object",
                "properties": {
                    "customer_name": {
                        "type": "string",
                        "description": "The name of the customer to search for"
                    }
                },
                "required": ["customer_name"]
            }
        ),
        Tool(
            name="debug_accounts",
            description="Debug tool: List ALL accounts with their types and subtypes to help diagnose account detection issues",
            inputSchema={
                "type": "object",
                "properties": {
                    "show_archived": {
                        "type": "boolean",
                        "description": "Whether to include archived accounts in the output (default: false)",
                        "default": False
                    }
                },
                "additionalProperties": False
            }
        )
    ]

@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls"""
    global wave_client
    
    if not wave_client:
        return [TextContent(type="text", text="Error: Wave client not initialized. Please check your WAVE_ACCESS_TOKEN environment variable.")]
    
    try:
        if name == "set_business":
            business_id = arguments["business_id"]
            wave_client.business_id = business_id
            decoded_business_id = decode_business_id(business_id)
            return [TextContent(type="text", text=f"Set active business to: {decoded_business_id}")]
        
        elif name == "get_expense_accounts":
            if not wave_client.business_id:
                return [TextContent(type="text", text="Error: No business selected. Use set_business tool first.")]
            
            accounts = await wave_client.get_accounts(wave_client.business_id)
            expense_accounts = [
                acc["node"] for acc in accounts 
                if acc["node"]["type"]["name"] in ["Expenses", "EXPENSE", "COST_OF_GOODS_SOLD"]
                and not acc["node"]["isArchived"]
            ]
            
            if not expense_accounts:
                return [TextContent(type="text", text="No expense accounts found in this business.")]
            
            result = f"📊 **Available Expense Accounts** ({len(expense_accounts)} found):\n\n"
            for acc in expense_accounts:
                result += f"**{acc['name']}**\n"
                result += f"  - ID: `{acc['id']}`\n"
                result += f"  - Type: {acc['subtype']['name']}\n\n"
            
            return [TextContent(type="text", text=result)]
        
        elif name == "search_vendor":
            if not wave_client.business_id:
                return [TextContent(type="text", text="Error: No business selected. Use set_business tool first.")]
            
            vendor_name = arguments["vendor_name"]
            
            vendors = await wave_client.get_vendors(wave_client.business_id)
            
            # Search for existing vendor
            for vendor in vendors:
                if vendor["node"]["name"].lower() == vendor_name.lower():
                    return [TextContent(type="text", text=f"✅ Found existing vendor: **{vendor['node']['name']}**\n- ID: `{vendor['node']['id']}`\n- Email: {vendor['node']['email'] or 'Not provided'}")]
            
            # Vendor not found - provide guidance for manual creation
            return [TextContent(type="text", text=f"❌ Vendor '{vendor_name}' not found.\n\n💡 **To add this vendor:**\n1. Go to Wave's web interface\n2. Navigate to Purchases → Vendors\n3. Click 'Add a vendor'\n4. Enter vendor details\n5. Try creating the expense again")]
        
        elif name == "create_expense_from_receipt":
            if not wave_client.business_id:
                return [TextContent(type="text", text="Error: No business selected. Use set_business tool first.")]
            
            vendor_name = arguments.get("vendor_name")
            amount = arguments["amount"]
            date = arguments["date"]
            category = arguments.get("category", "General Expenses")
            description = arguments.get("description", "")
            receipt_text = arguments["receipt_text"]
            payment_account = arguments.get("payment_account")
            
            # Handle optional vendor
            vendor_id = None
            if vendor_name:
                # Try to find existing vendor
                vendors = await wave_client.get_vendors(wave_client.business_id)
                for vendor in vendors:
                    if vendor["node"]["name"].lower() == vendor_name.lower():
                        vendor_id = vendor["node"]["id"]
                        break
                
                if not vendor_id:
                    # Vendor not found but we'll still create the expense
                    pass
            
            # Find appropriate expense account using improved matching
            accounts = await wave_client.get_accounts(wave_client.business_id)
            expense_account_id, expense_account_name, match_score, match_explanation = wave_client.find_best_account_match(
                category, accounts, "Expenses", description
            )
            
            if not expense_account_id:
                return [TextContent(type="text", text="Error: No expense accounts found")]
            
            # Find an anchor account (bank/credit card)
            anchor_accounts = await wave_client.get_anchor_accounts(wave_client.business_id)
            if not anchor_accounts:
                return [TextContent(type="text", text="Error: No bank or credit card accounts found to pay from")]
            
            # Try to find the specified payment account
            anchor_account_id = None
            anchor_account_name = None
            
            if payment_account:
                # Search for matching account by name (case-insensitive)
                for account in anchor_accounts:
                    if account["name"].lower() == payment_account.lower():
                        anchor_account_id = account["id"]
                        anchor_account_name = account["name"]
                        break
                
                if not anchor_account_id:
                    # Payment account not found, list available accounts
                    available_accounts = [acc["name"] for acc in anchor_accounts]
                    return [TextContent(type="text", text=f"❌ Payment account '{payment_account}' not found.\\n\\n💡 **Available payment accounts:**\\n" + "\\n".join([f"- {acc}" for acc in available_accounts]))]
            
            # Use the first available anchor account if none specified or not found
            if not anchor_account_id:
                anchor_account_id = anchor_accounts[0]["id"]
                anchor_account_name = anchor_accounts[0]["name"]
            
            # Create the expense (vendor_id can be None)
            expense_result = await wave_client.create_expense(
                business_id=wave_client.business_id,
                vendor_id=vendor_id,
                expense_account_id=expense_account_id,
                anchor_account_id=anchor_account_id,
                amount=amount,
                date=date,
                description=description or f"Expense - {vendor_name or 'Unknown Vendor'}"
            )
            
            if expense_result["didSucceed"]:
                transaction_id = expense_result["transaction"]["id"]
                vendor_text = f"- Vendor: {vendor_name}\n" if vendor_name else "- Vendor: Not specified (can be added later in Wave)\n"
                if vendor_name and not vendor_id:
                    vendor_text += f"  ⚠️ Note: Vendor '{vendor_name}' not found in Wave - create manually if needed\n"
                
                # Show payment account with context
                payment_text = f"- Paid from: {anchor_account_name}"
                if payment_account and payment_account.lower() == anchor_account_name.lower():
                    payment_text += " ✅"  # Indicate the requested account was used
                elif payment_account:
                    payment_text += f" (requested: {payment_account}, but using default)"
                
                # Add category matching explanation with enhanced debugging for low scores
                category_explanation = ""
                if match_score < 1.0:  # Not an exact match
                    category_explanation = f"- Category: {category} → {expense_account_name}\n  💡 {match_explanation}"
                    # Add extra info for very low confidence matches
                    if match_score < 0.4:
                        category_explanation += f" (Confidence: {match_score:.1%})"
                    category_explanation += "\n"
                else:
                    category_explanation = f"- Category: {expense_account_name}\n"
                
                return [TextContent(type="text", text=f"✅ Successfully created expense:\n- Amount: ${amount}\n{vendor_text}- Date: {date}\n{payment_text}\n{category_explanation}- Transaction ID: {transaction_id}")]
            else:
                errors = ", ".join([f"{err['path']}: {err['message']}" for err in expense_result["inputErrors"]])
                return [TextContent(type="text", text=f"❌ Failed to create expense: {errors}")]
        
        elif name == "list_businesses":
            page = arguments.get("page", 1)
            page_size = arguments.get("page_size", 10)
            
            business_info = await wave_client.get_business_info(page=page, page_size=page_size)
            businesses = business_info["businesses"]["edges"]
            page_info = business_info["businesses"]["pageInfo"]
            
            if not businesses:
                return [TextContent(type="text", text="No businesses found.")]
            
            result = f"📊 **Wave Businesses** (Page {page_info['currentPage']} of {page_info['totalPages']}, Total: {page_info['totalCount']})\n\n"
            
            for business in businesses:
                node = business["node"]
                status_indicators = []
                if node.get("isPersonal"):
                    status_indicators.append("👤 Personal")
                if node.get("isClassicAccounting"):
                    status_indicators.append("📊 Classic")
                if node.get("isArchived"):
                    status_indicators.append("🗃️ Archived")
                
                status = " | ".join(status_indicators) if status_indicators else "🏢 Business"
                result += f"**{node['name']}**\n"
                result += f"  - ID: `{node['id']}`\n"
                result += f"  - Type: {status}\n\n"
            
            if page_info['currentPage'] < page_info['totalPages']:
                result += f"💡 Use `list_businesses` with `page: {page_info['currentPage'] + 1}` to see more businesses."
            
            return [TextContent(type="text", text=result)]
        
        elif name == "get_income_accounts":
            if not wave_client.business_id:
                return [TextContent(type="text", text="Error: No business selected. Use set_business tool first.")]
            
            accounts = await wave_client.get_accounts(wave_client.business_id)
            income_accounts = [
                acc["node"] for acc in accounts 
                if acc["node"]["type"]["name"] in ["Income", "INCOME"]
                and not acc["node"]["isArchived"]
            ]
            
            if not income_accounts:
                return [TextContent(type="text", text="No income accounts found in this business.")]
            
            result = f"💰 **Available Income Accounts** ({len(income_accounts)} found):\n\n"
            for acc in income_accounts:
                result += f"**{acc['name']}**\n"
                result += f"  - ID: `{acc['id']}`\n"
                result += f"  - Type: {acc['subtype']['name']}\n\n"
            
            return [TextContent(type="text", text=result)]
        
        elif name == "search_customer":
            if not wave_client.business_id:
                return [TextContent(type="text", text="Error: No business selected. Use set_business tool first.")]
            
            customer_name = arguments["customer_name"]
            
            customers = await wave_client.get_customers(wave_client.business_id)
            
            # Search for existing customer
            for customer in customers:
                if customer["node"]["name"].lower() == customer_name.lower():
                    return [TextContent(type="text", text=f"✅ Found existing customer: **{customer['node']['name']}**\n- ID: `{customer['node']['id']}`\n- Email: {customer['node']['email'] or 'Not provided'}")]
            
            # Customer not found - provide guidance
            return [TextContent(type="text", text=f"❌ Customer '{customer_name}' not found.\n\n💡 **To add this customer:**\n1. Go to Wave's web interface\n2. Navigate to Sales → Customers\n3. Click 'Add a customer'\n4. Enter customer details\n5. Try creating the income transaction again")]
        
        elif name == "create_income_from_payment":
            if not wave_client.business_id:
                return [TextContent(type="text", text="Error: No business selected. Use set_business tool first.")]
            
            customer_name = arguments.get("customer_name")
            amount = arguments["amount"]
            date = arguments["date"]
            income_category = arguments.get("income_category", "Sales")
            description = arguments.get("description", "")
            payment_description = arguments["payment_description"]
            deposit_to_account = arguments.get("deposit_to_account")
            
            # Handle optional customer
            customer_id = None
            if customer_name:
                # Try to find existing customer
                customers = await wave_client.get_customers(wave_client.business_id)
                for customer in customers:
                    if customer["node"]["name"].lower() == customer_name.lower():
                        customer_id = customer["node"]["id"]
                        break
                
                if not customer_id:
                    # Customer not found but we'll still create the income
                    pass
            
            # Find appropriate income account using improved matching
            accounts = await wave_client.get_accounts(wave_client.business_id)
            # Combine description and payment_description for apartment context
            context_text = f"{description} {payment_description}"
            income_account_id, income_account_name, match_score, match_explanation = wave_client.find_best_account_match(
                income_category, accounts, "Income", context_text
            )
            
            if not income_account_id:
                return [TextContent(type="text", text="Error: No income accounts found")]
            
            # Find an anchor account (bank account for deposits)
            anchor_accounts = await wave_client.get_anchor_accounts(wave_client.business_id)
            if not anchor_accounts:
                return [TextContent(type="text", text="Error: No bank accounts found to deposit to")]
            
            # Try to find the specified deposit account
            anchor_account_id = None
            anchor_account_name = None
            
            if deposit_to_account:
                # Search for matching account by name (case-insensitive)
                for account in anchor_accounts:
                    if account["name"].lower() == deposit_to_account.lower():
                        anchor_account_id = account["id"]
                        anchor_account_name = account["name"]
                        break
                
                if not anchor_account_id:
                    # Deposit account not found, list available accounts
                    available_accounts = [acc["name"] for acc in anchor_accounts]
                    return [TextContent(type="text", text=f"❌ Deposit account '{deposit_to_account}' not found.\n\n💡 **Available deposit accounts:**\n" + "\n".join([f"- {acc}" for acc in available_accounts]))]
            
            # Use the first available anchor account if none specified or not found
            if not anchor_account_id:
                anchor_account_id = anchor_accounts[0]["id"]
                anchor_account_name = anchor_accounts[0]["name"]
            
            # Create the income (customer_id can be None)
            income_result = await wave_client.create_income(
                business_id=wave_client.business_id,
                customer_id=customer_id,
                income_account_id=income_account_id,
                anchor_account_id=anchor_account_id,
                amount=amount,
                date=date,
                description=description or payment_description
            )
            
            if income_result["didSucceed"]:
                transaction_id = income_result["transaction"]["id"]
                customer_text = f"- Customer: {customer_name}\n" if customer_name else "- Customer: Not specified (can be added later in Wave)\n"
                if customer_name and not customer_id:
                    customer_text += f"  ⚠️ Note: Customer '{customer_name}' not found in Wave - create manually if needed\n"
                
                # Show deposit account with context
                deposit_text = f"- Deposited to: {anchor_account_name}"
                if deposit_to_account and deposit_to_account.lower() == anchor_account_name.lower():
                    deposit_text += " ✅"  # Indicate the requested account was used
                elif deposit_to_account:
                    deposit_text += f" (requested: {deposit_to_account}, but using default)"
                
                # Add category matching explanation with enhanced debugging for low scores
                category_explanation = ""
                if match_score < 1.0:  # Not an exact match
                    category_explanation = f"- Category: {income_category} → {income_account_name}\n  💡 {match_explanation}"
                    # Add extra info for very low confidence matches
                    if match_score < 0.4:
                        category_explanation += f" (Confidence: {match_score:.1%})"
                    category_explanation += "\n"
                else:
                    category_explanation = f"- Category: {income_account_name}\n"
                
                return [TextContent(type="text", text=f"✅ Successfully created income transaction:\n- Amount: ${amount}\n{customer_text}- Date: {date}\n{deposit_text}\n{category_explanation}- Transaction ID: {transaction_id}")]
            else:
                errors = ", ".join([f"{err['path']}: {err['message']}" for err in income_result["inputErrors"]])
                return [TextContent(type="text", text=f"❌ Failed to create income transaction: {errors}")]
        
        elif name == "debug_accounts":
            if not wave_client.business_id:
                return [TextContent(type="text", text="Error: No business selected. Use set_business tool first.")]
            
            show_archived = arguments.get("show_archived", False)
            
            # Get all accounts
            accounts = await wave_client.get_accounts(wave_client.business_id)
            
            # Group accounts by type
            accounts_by_type = {}
            all_types = set()
            all_subtypes = set()
            
            for acc in accounts:
                node = acc["node"]
                if not show_archived and node["isArchived"]:
                    continue
                    
                account_type = node["type"]["name"]
                subtype = node.get("subtype", {}).get("name", "N/A")
                
                all_types.add(account_type)
                all_subtypes.add(subtype)
                
                if account_type not in accounts_by_type:
                    accounts_by_type[account_type] = []
                
                accounts_by_type[account_type].append({
                    "name": node["name"],
                    "subtype": subtype,
                    "archived": node["isArchived"],
                    "id": node["id"]
                })
            
            # Build the debug output
            result = "🔍 **Account Debug Information**\n\n"
            result += f"**Summary:**\n"
            result += f"- Total account types: {len(all_types)}\n"
            result += f"- Total subtypes: {len(all_subtypes)}\n"
            result += f"- Show archived: {show_archived}\n\n"
            
            result += f"**All Account Types Found:** {', '.join(sorted(all_types))}\n\n"
            result += f"**All Subtypes Found:** {', '.join(sorted(all_subtypes))}\n\n"
            
            # Show accounts grouped by type
            for account_type in sorted(accounts_by_type.keys()):
                accounts_list = accounts_by_type[account_type]
                result += f"## {account_type} ({len(accounts_list)} accounts)\n\n"
                
                for acc in accounts_list:
                    archived_flag = " 🗃️ ARCHIVED" if acc["archived"] else ""
                    result += f"- **{acc['name']}**{archived_flag}\n"
                    result += f"  - Subtype: {acc['subtype']}\n"
                    result += f"  - ID: `{acc['id']}`\n\n"
            
            # Special focus on income accounts
            income_accounts = accounts_by_type.get("Income", [])
            if income_accounts:
                result += f"🎯 **Income Account Analysis:**\n"
                result += f"Found {len(income_accounts)} Income accounts:\n"
                for acc in income_accounts:
                    result += f"- {acc['name']} (subtype: {acc['subtype']})\n"
            else:
                result += f"⚠️ **NO INCOME ACCOUNTS FOUND** - This explains the rental matching issue!\n"
                result += f"Check if your rental income accounts have a different type name.\n"
            
            return [TextContent(type="text", text=result)]
        
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    except Exception as e:
        logger.error(f"Error in tool {name}: {str(e)}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    """Main entry point"""
    global wave_client
    
    # Get access token from environment
    access_token = os.getenv("WAVE_ACCESS_TOKEN")
    if not access_token:
        logger.error("WAVE_ACCESS_TOKEN environment variable is required")
        return
    
    # Initialize Wave client
    wave_client = WaveClient(access_token)
    
    # Set business ID if provided
    business_id = os.getenv("WAVE_BUSINESS_ID")
    if business_id:
        logger.info(f"Using business ID: {business_id}")
        wave_client.business_id = base64.b64encode(f"Business:{business_id}".encode())
    else:
        logger.info("No business ID provided, will need to set via tool")
    
    # Test connection
    try:
        business_info = await wave_client.get_business_info()
        businesses = business_info["businesses"]["edges"]
        logger.info(f"Connected to Wave API. Found {len(businesses)} businesses.")
        
        if not wave_client.business_id and businesses:
            # Auto-select first business if only one
            if len(businesses) == 1:
                wave_client.business_id = businesses[0]["node"]["id"]
                logger.info(f"Auto-selected business: {businesses[0]['node']['name']} ({decode_business_id(wave_client.business_id)})")
        
    except Exception as e:
        logger.error(f"Failed to connect to Wave API: {e}")
        return
    
    # Start the server
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, 
            write_stream, 
            InitializationOptions(
                server_name="wave-accounting",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=type('NotificationOptions', (), {
                        'resources_changed': False,
                        'tools_changed': False,
                        'prompts_changed': False
                    })(),
                    experimental_capabilities={}
                )
            )
        )

if __name__ == "__main__":
    asyncio.run(main())
