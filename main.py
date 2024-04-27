from openai import OpenAI
import telebot
import json
import ast
import os

if not os.environ.get("PRODUCTION"):
    from dotenv import load_dotenv
    load_dotenv()

bot = telebot.TeleBot(os.environ["BOT_TOKEN"])
client = OpenAI(api_key=os.environ["OPENAI_API"])

context_prompt = '''
[ROLE]
Your role is "Flower Shop" Assistant. You are managing chat, where clients may ask different questions. Your language style is proffesional, but friendly.

[CONTEXT]
Our shop sells only 3 types of flowers:
- Roses: 5 dollars per item;
- Tulips: 4 dollars per item;
- Orchids: 3 dollars per item;

Our shop address: Kyiv, Prorizna Street 155.

Work time:
- From Monday to Friday 9:00-18:00
- Saturday 10:00-16:00
- Sunday is day off

Delivery:
We provide delivery only in Kyiv city through "Nova Poshta" delivery company. If total amount of order is equal or above 100 dollars - customer can get a free delivery. Otherwise, ship cost is according to "Nova Poshta" tariffs and paid by customer.

Decoration:
Our shop also can package customers flowers in a bouquet. Small decorative items(such as strip or glitter) can be added for free.

[GOAL]
Your goal is to answer users questions only regarding Flower Shop. Gently refuese to engage in conversations that are not related to Flower Shop bussines.
Also, your goal is to try "sell" the flowers. But don't be too pushy. If customer wants delivery - ask for destination and contact information. 
'''

# define assistant and function to pass customer info to manager
assistant = client.beta.assistants.create(
    name="Flower Shop Assistant",
    instructions=context_prompt,
    model="gpt-4-turbo",
    tools=[
        {
            "type": "function",
            "function": {
                "name": "pass_to_manager",
                "description": "Pass order information for delivery to a manager.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "Customer delivery address, e.g., Privozny Street 23/65"
                        },
                        "contact": {
                            "type": "string",
                            "description": "Customer contact information, e.g., Taras Shevchenko, +360660000007"
                        },
                        "order": {
                            "type": "string",
                            "description": "Order information, e.g., rose: 1, tulips: 2"
                        },
                        "comment": {
                            "type": "string",
                            "description": "Any additional information about order, e.g., customer comments"
                        }
                    },
                    "required": ["location", "contact", "order"]
                }
            }
        }
    ]
)

# multi chat threads
threads = {}

# function to pass delivery order info to a manager
def pass_to_manager(location, contact, order, comment=None):
    order_info = f"Contact: {contact}\nOrder: {order}\nDestination: {location}\nComment: {comment}"
    # this info can be redirected to telegram chat with Manager
    bot.send_message(448272985, order_info)
    return order_info


# Start conversation handler
@bot.message_handler(commands=['start'])
def help_command(message):
    first_message = "I'm here to assist you with questions specifically about our Flower Shop. If you'd like information on our flower selection, prices, or any services, please let me know how I can help!"
    bot.send_message(message.chat.id, first_message, parse_mode="Markdown")

    # Create this user thread
    thread = client.beta.threads.create()
    threads[message.from_user.id] = thread

    # Add first message from assistant to thread
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="assistant",
        content=first_message
    )


# All text  handler
@bot.message_handler(content_types=["text"])
def txt(tg_message):
    # get this user thread
    thread = threads[tg_message.from_user.id]
    
    # place user message in thread
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=tg_message.text
    )

    # run assistant answer
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id,
        assistant_id=assistant.id
    )

    # answer user if status is completed
    if run.status == 'completed': 
        messages = client.beta.threads.messages.list(
            thread_id=thread.id
        )
        message = client.beta.threads.messages.retrieve(
            thread_id=thread.id,
            message_id=messages.first_id
        )
        print(message.content[0].text.value)
        bot.reply_to(tg_message, message.content[0].text.value, parse_mode="Markdown")
    else:
        print(run.status)


    # Define the list to store tool outputs
    tool_outputs = []
    
    # Loop through each tool in the required action section
    if run.required_action:
        for tool in run.required_action.submit_tool_outputs.tool_calls:
            if tool.function.name == "pass_to_manager":
                f_args = ast.literal_eval(tool.function.arguments)
                print(f_args)
                tool_outputs.append({
                    "tool_call_id": tool.id,
                    "output": pass_to_manager(*f_args)
                })
    
    # Submit all tool outputs at once after collecting them in a list
    if tool_outputs:
        try:
            run = client.beta.threads.runs.submit_tool_outputs_and_poll(
            thread_id=thread.id,
            run_id=run.id,
            tool_outputs=tool_outputs
        )
            print("Tool outputs submitted successfully.")
        except Exception as e:
            print("Failed to submit tool outputs:", e)
        else:
            print("No tool outputs to submit.")
        
        if run.status == 'completed':
            messages = client.beta.threads.messages.list(
                thread_id=thread.id
            )
            message = client.beta.threads.messages.retrieve(
                thread_id=thread.id,
                message_id=messages.first_id
            )
            bot.reply_to(tg_message, message.content[0].text.value)
    else:
        print(run.status)


if __name__ == "__main__":
    # Bot main thread
    print("starting bot...")
    bot.infinity_polling()
