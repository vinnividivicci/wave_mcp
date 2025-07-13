# Wave Accounting MCP Server

A Model Context Protocol (MCP) server that integrates Claude with Wave Accounting to automate expense tracking and income transaction creation.

## Features

- 📸 **Expense Creation from Receipts**: Automatically extract and create expenses from receipt text
- 💰 **Income Transaction Creation**: Create income transactions from payment data
- 🏢 **Multi-Business Support**: Manage multiple Wave businesses seamlessly
- 🔍 **Vendor & Customer Search**: Find existing vendors and customers
- 📊 **Account Management**: List and categorize transactions with proper accounts
- 🔄 **Real-time Integration**: Direct connection to Wave's GraphQL API

## Prerequisites

- Python 3.8 or higher
- Wave Business account with API access
- Claude Desktop application
- Wave OAuth2 access token

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/wave_mcp.git
cd wave_mcp
```

2. Activate python venv, install dependencies:
```bash
python -m venv venv
source ./venv/bin/activate
pip install -r requirements.txt
```

3. Create a `.env` file:
```env
WAVE_ACCESS_TOKEN=your_wave_oauth2_access_token_here
```

## Getting Your Wave Access Token

1. Log in to your [Wave account](https://www.waveapps.com)
2. Navigate to **Settings** → **API Access** (only available in Wave Business account)
3. Create a new OAuth2 application
4. Generate an OAuth2 Bearer access token with appropriate permissions

> **Note**: Wave API access may require approval. Check Wave's current developer program status.

> **Note2**: If you want to test without Wave Business account, login to waveapps.com and grab the Bearer token from the webpage's GraphQL requests. It works the same, for a limited time.

## Configuration

### Claude Desktop Setup

Add the server to your Claude Desktop configuration:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "wave-accounting": {
      "command": "/absolute/path/to/wave_mcp/venv/bin/python",
      "args": ["/absolute/path/to/wave_mcp/mcp_server.py"],
      "env": {
        "WAVE_ACCESS_TOKEN": "your_wave_oauth2_access_token_here",
        "WAVE_BUSINESS_ID": "Your Wave business ID (optional, Claude will ask for it if not configured)"
      }
    }
  }
}
```
Restart Claude Desktop after saving the configuration.

> **Note**: You can find business id (36-char UUID) in your waveapp webpage URL.

## Usage Examples

### Creating an Expense from a Receipt

```
I have a receipt from Office Depot for $45.99 dated March 15, 2024. 
It's for office supplies - printer paper and pens.
```

### Creating Income from Payment

```
Received payment of $1,500 from ABC Company on March 20, 2024 
for consulting services invoice #1234.
```

### Listing Available Accounts

```
Show me my expense accounts in Wave.
```

### Setting Active Business (Multi-Business Accounts)

```
List my Wave businesses and set the active one.
```

## Available MCP Tools

### Expense Management
- **`create_expense_from_receipt`**: Create expenses from receipt text
- **`search_vendor`**: Search for existing vendors
- **`get_expense_accounts`**: List available expense accounts

### Income Management
- **`create_income_from_payment`**: Create income transactions
- **`search_customer`**: Search for existing customers
- **`get_income_accounts`**: List available income accounts

### Business Management
- **`set_business`**: Set the active business
- **`list_businesses`**: List all available businesses

### Debugging
- **`debug_accounts`**: List all accounts with types and subtypes for troubleshooting

## Important Notes

### Vendor and Customer Management
- Vendors and customers must be created manually in Wave's web interface
- The API supports searching existing vendors/customers but not creating new ones
- Transactions can be created without vendors/customers and linked later

### Limitations
- Wave API doesn't support attaching receipt images/PDFs
- Maximum 2 simultaneous API requests (Wave rate limiting)
- OAuth2 tokens may expire and need refreshing

## Development

### Running Tests
```bash
# Currently no test suite - testing via Claude Desktop integration
python mcp_server.py
```

### Project Structure
```
wave_mcp/
├── mcp_server.py          # Main MCP server implementation
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── LICENSE               # MIT License
├── CLAUDE.md             # Claude-specific instructions
├── .env                  # Your API credentials (not tracked)
└── docs/
    └── wave_api_reference.md  # Wave API documentation
```

## Troubleshooting

### "Wave client not initialized"
- Verify your `WAVE_ACCESS_TOKEN` is set correctly
- Check that the token has valid permissions

### "No business selected"
- Use the `list_businesses` tool to see available businesses
- Set the active business with `set_business`

### MCP Server Not Available in Claude
- Ensure the path in `claude_desktop_config.json` is absolute
- Verify Python and all dependencies are installed
- Restart Claude Desktop

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built for use with [Claude Desktop](https://claude.ai)
- Integrates with [Wave Accounting](https://www.waveapps.com)
- Uses the [Model Context Protocol](https://modelcontextprotocol.io)

## Security

- Never commit your `.env` file or API keys
- Use environment variables for all sensitive data
- Regularly rotate your API tokens
- Follow Wave's security best practices