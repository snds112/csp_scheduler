from constraint import Problem, AllDifferentConstraint
from datetime import datetime, timedelta
import random
import time

class Scheduler:
    def __init__(self, reservations_data, places_config):
        self.reservations_data = reservations_data
        # Store original reservation details keyed by ID for easy lookup
        self._reservations_by_id = {res['id']: res for res in reservations_data}
        self.places_config = places_config
        # Helper to store scheduled assignments (includes auto-approved and CSP-solved)
        self.scheduled_assignments = {}

    def _parse_time_slot(self, day_str, time_str):
        """Converts day and time strings to a datetime object for easier comparison."""
        return datetime.strptime(f"{day_str} {time_str}", "%Y-%m-%d %H:%M")

    def _do_times_overlap(self, start1, end1, start2, end2):
        """Checks if two time periods overlap."""
        return max(start1, start2) < min(end1, end2)

    def _get_place_type(self, place_id):
        """Helper to categorize place IDs, handling None for flexible requests."""
        if place_id is None:
            return 'unknown' # Represents a flexible request without a specified place type
        elif 1 <= place_id <= 24:
            return 'pc_desk'
        elif 26 <= place_id <= 45:  # Updated for individual lower floor desks
            return 'lower_floor'
        elif place_id in [101, 102, 103]:
            return 'room'
        return 'unknown' # Fallback for any other unexpected place_id

    def _create_scheduling_problem_with_strategy(self, strategy_level):
        """
        Creates and configures the CSP problem based on the given strategy level.
        Strategy levels define which places are available for assignment.
        """
        problem = Problem()
        # Reset scheduled_assignments for each attempt to only include fixed ones
        # and then add solutions from CSP.
        self.scheduled_assignments = {}

        coworking_pc_desks = self.places_config['coworking_pc_desks']
        lower_floor_desks = self.places_config['lower_floor_desks'] 
        room_ids = [self.places_config['room_1']['id'], self.places_config['room_2']['id'], self.places_config['room_3']['id']]

        # Separate available places by type for easier filtering
        all_pc_desks = set(coworking_pc_desks)
        all_non_pc_desks = set(lower_floor_desks).union(set(room_ids)) # Lower floor desks and rooms are non-PC

        # First, add all accepted/formation reservations to scheduled_assignments
        pending_reservation_ids = []
        for reservation in self.reservations_data:
            res_id = reservation['id']
            formation_id = reservation['formation_id']
            request_status = reservation['request_status']

            if request_status == 'accepted' or formation_id:
                start_dt = self._parse_time_slot(reservation['day'], reservation['start_time'])
                end_dt = self._parse_time_slot(reservation['day'], reservation['end_time'])
                self.scheduled_assignments[res_id] = {
                    'place_id': reservation['place_id'],
                    'start_time': start_dt,
                    'end_time': end_dt,
                    'status': 'accepted'
                }
            elif request_status == 'pending':
                pending_reservation_ids.append(res_id)
            # Rejected reservations are ignored by the scheduler

        # Now, define variables and constraints for pending reservations
        for res_id in pending_reservation_ids:
            original_res = self._reservations_by_id[res_id]
            
            # Determine the domain of available places based on strategy and original request
            possible_places_for_this_res = []
            requested_place_type = self._get_place_type(original_res['place_id'])
            needs_pc = original_res.get('needPc', True) # Default to True if not specified

            if strategy_level == 1: # Prioritize PC Desks
                if needs_pc:
                    # Only PC desks
                    if requested_place_type == 'pc_desk' or requested_place_type == 'unknown':
                        possible_places_for_this_res = list(coworking_pc_desks)
                else: # Does NOT need PC
                    # Only non-PC desks (if explicitly requested lower_floor or unknown, try to give non-PC)
                    if requested_place_type == 'lower_floor' or requested_place_type == 'unknown':
                        # For Strategy 1, if no PC is needed, only PC desks are considered by default.
                        # This means if 'unknown' and no PC, it might not find a place here,
                        # which is fine as it will go to strategy 2/3.
                        # If a specific lower_floor desk was requested, allow it.
                        if original_res['place_id'] in lower_floor_desks:
                             possible_places_for_this_res = [original_res['place_id']]
                        # Otherwise, Strategy 1, not needing PC, for general requests will struggle.
                        # This behavior aligns with Strategy 1's strictness.
            elif strategy_level == 2: # PC Desks + Lower Floor
                if needs_pc:
                    # PC desks. If requested lower floor or unknown, try PC first then lower floor
                    if requested_place_type == 'pc_desk':
                        possible_places_for_this_res = list(coworking_pc_desks) # PC first for 'unknown'
                    elif requested_place_type == 'lower_floor':
                        possible_places_for_this_res = list(lower_floor_desks)
                    elif requested_place_type == 'unknown':
                        possible_places_for_this_res == list(lower_floor_desks) + list(coworking_pc_desks)
                else: # Does NOT need PC
                    # Prefer non-PC desks if flexible, or if lower floor requested
                    if requested_place_type == 'lower_floor' or requested_place_type == 'unknown':
                        possible_places_for_this_res = list(lower_floor_desks) + list(coworking_pc_desks) # Non-PC first, then PC if needed
                    elif requested_place_type == 'pc_desk': # If they specifically asked for a PC desk but don't need PC, still allow it
                        possible_places_for_this_res = list(coworking_pc_desks)

            elif strategy_level == 3: # All Places (PC Desks + Lower Floor + Rooms)
                if needs_pc:
                    # Prioritize PC desks, then lower floor, then rooms for flexible requests
                    if requested_place_type == 'pc_desk' :
                        possible_places_for_this_res = list(coworking_pc_desks) 
                    elif requested_place_type == 'lower_floor':
                        possible_places_for_this_res = list(lower_floor_desks) + list(coworking_pc_desks) + list(room_ids) # Lower floor preferred, but can go to others
                    elif requested_place_type == 'room':
                        possible_places_for_this_res = list(room_ids)  # Room preferred
                    elif requested_place_type == 'unknown':
                         possible_places_for_this_res = list(coworking_pc_desks) + list(lower_floor_desks) + list(room_ids)
                else: # Does NOT need PC
                    # Prioritize non-PC desks (lower floor, rooms), then PC desks if no other options
                    if requested_place_type == 'pc_desk':
                        possible_places_for_this_res = list(coworking_pc_desks) # Still allow PC if specifically requested
                    elif requested_place_type == 'lower_floor' or requested_place_type == 'unknown':
                        possible_places_for_this_res = list(lower_floor_desks) + list(room_ids) + list(coworking_pc_desks) # Prefer non-PC first
                    elif requested_place_type == 'room':
                        possible_places_for_this_res = list(room_ids) # Room preferred
            
            # Filter out places that are of the wrong type for 'needs_pc' IF the original request was flexible (place_id is None)
            # If a specific place was requested (e.g., place_id=5 for PC, or place_id=30 for non-PC), we respect that,
            # regardless of 'needs_pc', as it's a hard constraint from the user.
            if original_res['place_id'] is None: # Only apply 'needsPc' preference for flexible requests
                if needs_pc:
                    possible_places_for_this_res = [p for p in possible_places_for_this_res if p in all_pc_desks ] # Needs PC, so remove non-PC only if it makes sense for the strategy
                    # Refinement: If needs_pc, only allow PC desks in strategy 1. For strategy 2/3 allow other if PC is full
                    if needs_pc:
                        if strategy_level == 1:
                            possible_places_for_this_res = [p for p in possible_places_for_this_res if p in all_pc_desks]
                        elif strategy_level in [2,3]:
                            # For non-PC needs, we prioritize non-PC desks. We let flexible requests try all.
                            # The filtering for 'needs_pc' and 'place_type' should already handle this.
                            pass # The logic above already attempts to prioritize/exclude based on strategy and needPc
                else: # Does NOT need PC
                    # Strictly prefer non-PC desks. Only fall back to PC desks if no non-PC available within the strategy.
                    # This means we should order `possible_places_for_this_res` to put non-PC desks first.
                    # The logic above already sets this order.
                    pass


            # Ensure the domain is not empty for pending variables
            if not possible_places_for_this_res:
                print(f"Warning: No possible places for res_id {res_id} under strategy {strategy_level}.")
                continue

            problem.addVariable(f'res_{res_id}_place', possible_places_for_this_res)

            # Constraint: A pending reservation cannot conflict with an already scheduled (fixed) reservation
            def create_fixed_conflict_constraint(current_res_id, fixed_res_details):
                current_start_dt = self._parse_time_slot(self._reservations_by_id[current_res_id]['day'], self._reservations_by_id[current_res_id]['start_time'])
                current_end_dt = self._parse_time_slot(self._reservations_by_id[current_res_id]['day'], self._reservations_by_id[current_res_id]['end_time'])

                fixed_place_id = fixed_res_details['place_id']
                fixed_start_dt = fixed_res_details['start_time']
                fixed_end_dt = fixed_res_details['end_time']

                return lambda assigned_place: \
                    not (assigned_place == fixed_place_id and
                         self._do_times_overlap(current_start_dt, current_end_dt, fixed_start_dt, fixed_end_dt))

            for fixed_res_id, fixed_details in self.scheduled_assignments.items():
                problem.addConstraint(
                    create_fixed_conflict_constraint(res_id, fixed_details),
                    (f'res_{res_id}_place',)
                )

        # Constraint: No two *pending* reservations can occupy the same place at the same time.
        actual_pending_var_names_in_problem = [var for var in problem._variables if var.startswith('res_') and var.endswith('_place')]

        for i, var_name1 in enumerate(actual_pending_var_names_in_problem):
            res_id1 = int(var_name1.split('_')[1])
            for var_name2 in actual_pending_var_names_in_problem[i+1:]:
                res_id2 = int(var_name2.split('_')[1])

                res1_start_dt = self._parse_time_slot(self._reservations_by_id[res_id1]['day'], self._reservations_by_id[res_id1]['start_time'])
                res1_end_dt = self._parse_time_slot(self._reservations_by_id[res_id1]['day'], self._reservations_by_id[res_id1]['end_time'])

                res2_start_dt = self._parse_time_slot(self._reservations_by_id[res_id2]['day'], self._reservations_by_id[res_id2]['start_time'])
                res2_end_dt = self._parse_time_slot(self._reservations_by_id[res_id2]['day'], self._reservations_by_id[res_id2]['end_time'])

                problem.addConstraint(
                    lambda place1, place2:
                        not (place1 == place2 and self._do_times_overlap(res1_start_dt, res1_end_dt, res2_start_dt, res2_end_dt)),
                    (var_name1, var_name2)
                )
        
        for res_id in pending_reservation_ids:
            if f'res_{res_id}_place' not in problem._variables:
                return None # This strategy cannot schedule all pending reservations


        return problem

    def solve(self):
        # Store initial pending reservation IDs for fallback
        initial_pending_ids = [res['id'] for res in self.reservations_data if res['request_status'] == 'pending']
        
        # Attempt CSP strategies
        for strategy_level in range(1, 4):
            print(f"\nAttempting scheduling with Strategy {strategy_level}...")
            self.problem = self._create_scheduling_problem_with_strategy(strategy_level)
            if self.problem:
                found_solution = None
                start_time = time.time() # Start timer for this strategy
                time_limit = 5 # Time limit for all strategies in this version
                
                try:
                    # Use getSolutionIter for all strategies to find the first solution quickly
                    for solution in self.problem.getSolutionIter():
                        found_solution = solution
                        # Break as soon as the first solution is found
                        break 
                        
                except Exception as e:
                    print(f"  An error occurred during Strategy {strategy_level} solving: {e}")
                    found_solution = None # No solution due to error

                # Check time limit specifically for Strategy 3 *after* attempting to find a solution
                if not found_solution and (time.time() - start_time) >= time_limit:
                    print(f"  Strategy {strategy_level} timed out after {time_limit} seconds without finding a solution.")
                    found_solution = None # Ensure it's explicitly None if it timed out

                if found_solution:
                    print(f"Solution found with Strategy {strategy_level}.")
                    return self._process_solution(found_solution)
                else:
                    print(f"No comprehensive solution found with Strategy {strategy_level}.")
            else:
                print(f"Problem setup failed for Strategy {strategy_level} (some pending reservations had no valid place options for this strategy).")
            print(f"Finished evaluating Strategy {strategy_level} results.")

        # Fallback: If no CSP strategy finds a full solution
        print("\nNo comprehensive solution found for all pending reservations via CSP. Attempting random assignment fallback...")
        return self._attempt_random_assignment_fallback(initial_pending_ids)


    def _process_solution(self, solution):
        """Processes a found solution and updates scheduled_assignments."""
        for var_name, assigned_place_id in solution.items():
            res_id = int(var_name.split('_')[1])
            original_res = self._reservations_by_id[res_id]
            self.scheduled_assignments[res_id] = {
                'place_id': assigned_place_id,
                'start_time': self._parse_time_slot(original_res['day'], original_res['start_time']),
                'end_time': self._parse_time_slot(original_res['day'], original_res['end_time']), 
                'status': 'accepted'
            }
        return self.scheduled_assignments

    def _attempt_random_assignment_fallback(self, initial_pending_ids):
        """
        Attempts to randomly assign places to pending reservations that were not
        scheduled by the CSP, respecting existing scheduled reservations.
        """
        # Start with the currently scheduled assignments (accepted/formation)
        current_schedule = {res_id: details for res_id, details in self.scheduled_assignments.items()}

        # Identify pending reservations that still need to be scheduled
        unscheduled_pending_ids = [res_id for res_id in initial_pending_ids if res_id not in current_schedule]
        
        random.shuffle(unscheduled_pending_ids) # Randomize order to give different reservations a chance

        coworking_pc_desks = self.places_config['coworking_pc_desks']
        lower_floor_desks = self.places_config['lower_floor_desks'] 
        room_ids = [self.places_config['room_1']['id'], self.places_config['room_2']['id'], self.places_config['room_3']['id']]
        
        all_possible_places = list(coworking_pc_desks) + list(lower_floor_desks) + list(room_ids)

        for res_id in unscheduled_pending_ids:
            original_res = self._reservations_by_id[res_id]
            res_start_dt = self._parse_time_slot(original_res['day'], original_res['start_time'])
            res_end_dt = self._parse_time_slot(original_res['day'], original_res['end_time'])
            needs_pc = original_res.get('needPc', True)

            # Determine preferred places based on original request, falling back to all if flexible
            requested_place_type = self._get_place_type(original_res['place_id'])
            
            candidate_places = []

            # Prioritize based on 'needPc'
            if needs_pc:
                # If PC is needed, prioritize PC desks
                candidate_places = list(coworking_pc_desks)
                # Filter out places that are definitely not suitable for PC if original was specific non-PC
                if requested_place_type == 'lower_floor' and original_res['place_id'] is not None:
                     candidate_places = [original_res['place_id']]
                elif requested_place_type == 'room' and original_res['place_id'] is not None:
                    candidate_places = [original_res['place_id']]
            else: # Does NOT need PC
                # Prioritize non-PC desks, then PC desks as a last resort
                candidate_places = list(lower_floor_desks) + list(room_ids) + list(coworking_pc_desks)
                # If a specific PC desk was requested, still allow it
                if requested_place_type == 'pc_desk' and original_res['place_id'] is not None:
                    candidate_places = [original_res['place_id']]
                
            # If the original request specified a place, that's the only candidate
            if original_res['place_id'] is not None:
                candidate_places = [original_res['place_id']]
            else:
                # If flexible, further refine candidates based on needs_pc
                if needs_pc:
                    # Filter for places that usually have a PC, or if flexible, allow any that *could* have one.
                    # The general ordering for flexible requests that need PC should prioritize PC desks first.
                    candidate_places = [p for p in candidate_places if p in coworking_pc_desks]
                    # If no PC desks, then allow other types only in higher strategies/fallback
                    if not candidate_places:
                        candidate_places = [p for p in all_possible_places if p in coworking_pc_desks] # Fallback to all PC desks if flexible
                else: # Does NOT need PC
                    # Prioritize non-PC desks
                    candidate_places = [p for p in candidate_places if p in lower_floor_desks or p in room_ids]
                    # If no non-PC desks, then allow PC desks as a last resort
                    if not candidate_places:
                        candidate_places = [p for p in all_possible_places if p in lower_floor_desks or p in room_ids or p in coworking_pc_desks]
            
            # Ensure no duplicates and randomize
            candidate_places = list(dict.fromkeys(candidate_places)) # Remove duplicates while preserving order
            random.shuffle(candidate_places)


            assigned = False
            for place_id_candidate in candidate_places:
                is_available = True
                # Check for conflicts with already scheduled reservations
                for sch_res_id, sch_details in current_schedule.items():
                    if sch_details['place_id'] == place_id_candidate and \
                       self._do_times_overlap(res_start_dt, res_end_dt, sch_details['start_time'], sch_details['end_time']):
                        is_available = False
                        break # Conflict found, this place is not available

                if is_available:
                    # Assign the place
                    current_schedule[res_id] = {
                        'place_id': place_id_candidate,
                        'start_time': res_start_dt,
                        'end_time': res_end_dt,
                        'status': 'scheduled_random_fallback' # Indicate it was assigned via fallback
                    }
                    assigned = True
                    print(f"  Randomly assigned Reservation ID {res_id} to Place {place_id_candidate}.")
                    break # Move to the next unscheduled reservation

            if not assigned:
                print(f"  Could not assign Reservation ID {res_id} even with random fallback (no available place found).")
                # Optionally, you might add it to current_schedule with a 'rejected' or 'unassigned' status
                # current_schedule[res_id] = {'status': 'unassigned'} # Or similar

        self.scheduled_assignments = current_schedule
        return self.scheduled_assignments


# --- Dummy Data (from your CSV example) ---
dummy_reservations_data = [
    {'id': 1, 'user_id': 101, 'place_id': 5, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '12:00', 'request_status': 'accepted', 'needPc': True},
    {'id': 2, 'user_id': 102, 'place_id': 25, 'formation_id': None, 'day': '2025-08-01', 'start_time': '10:00', 'end_time': '13:00', 'request_status': 'pending', 'needPc': False}, # Original lower floor request, explicitly no PC needed
    {'id': 3, 'user_id': 103, 'place_id': 101, 'formation_id': 'F001', 'day': '2025-08-02', 'start_time': '14:00', 'end_time': '17:00', 'request_status': 'accepted', 'needPc': False},
    {'id': 4, 'user_id': 104, 'place_id': 12, 'formation_id': None, 'day': '2025-08-02', 'start_time': '11:00', 'end_time': '16:00', 'request_status': 'pending', 'needPc': True}, # PC desk requested, PC needed
    {'id': 5, 'user_id': 105, 'place_id': 2, 'formation_id': None, 'day': '2025-08-03', 'start_time': '08:30', 'end_time': '10:30', 'request_status': 'accepted', 'needPc': True},
    {'id': 6, 'user_id': 106, 'place_id': 103, 'formation_id': 'F002', 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '17:00', 'request_status': 'accepted', 'needPc': False},
    {'id': 7, 'user_id': 107, 'place_id': 25, 'formation_id': None, 'day': '2025-08-05', 'start_time': '13:00', 'end_time': '16:00', 'request_status': 'pending', 'needPc': False}, # Original lower floor request, no PC needed
    {'id': 8, 'user_id': 108, 'place_id': 15, 'formation_id': None, 'day': '2025-08-05', 'start_time': '09:00', 'end_time': '12:00', 'request_status': 'accepted', 'needPc': True},
    {'id': 9, 'user_id': 109, 'place_id': 102, 'formation_id': None, 'day': '2025-08-06', 'start_time': '10:00', 'end_time': '12:00', 'request_status': 'rejected', 'needPc': False},
    {'id': 10, 'user_id': 110, 'place_id': 7, 'formation_id': None, 'day': '2025-08-06', 'start_time': '14:00', 'end_time': '17:00', 'request_status': 'accepted', 'needPc': True},
    # Adding a new pending request that might need to overflow
    {'id': 11, 'user_id': 111, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Flexible desk request, needs PC
    {'id': 12, 'user_id': 112, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 13, 'user_id': 113, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 14, 'user_id': 114, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 15, 'user_id': 115, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 16, 'user_id': 116, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 17, 'user_id': 117, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 18, 'user_id': 118, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 19, 'user_id': 119, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 20, 'user_id': 120, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 21, 'user_id': 121, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 22, 'user_id': 122, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 23, 'user_id': 123, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 24, 'user_id': 124, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # Another flexible desk request, needs PC
    {'id': 25, 'user_id': 125, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': False}, # This one will overflow, DOES NOT need PC
    {'id': 26, 'user_id': 126, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': False}, # New non-PC request
    {'id': 27, 'user_id': 127, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': False}, # New non-PC request
    {'id': 28, 'user_id': 128, 'place_id': None, 'formation_id': None, 'day': '2025-08-01', 'start_time': '09:00', 'end_time': '10:00', 'request_status': 'pending', 'needPc': True}, # New PC request
]

places_config = {
    'coworking_pc_desks': list(range(1, 25)), # 24 desks
    'lower_floor_desks': list(range(26, 46)), # 20 individual desks (IDs 26 to 45)
    'room_1': {'id': 101, 'capacity': 10},
    'room_2': {'id': 102, 'capacity': 10},
    'room_3': {'id': 103, 'capacity': 60},
}


if __name__ == "__main__":
    scheduler = Scheduler(dummy_reservations_data, places_config)
    solution = scheduler.solve()

    if solution:
        print("\n--- Final Scheduled Reservations ---")
        # Sort solutions by reservation ID for cleaner output
        sorted_solution_keys = sorted(solution.keys())
        for res_id in sorted_solution_keys:
            details = solution[res_id]
            original_res = scheduler._reservations_by_id[res_id]
            status = details.get('status', 'pending_scheduled')
            print(f"Reservation ID: {res_id}, User: {original_res['user_id']}, "
                  f"Assigned Place: {details['place_id']}, "
                  f"Original Requested Place: {'Any' if original_res['place_id'] is None else original_res['place_id']}, "
                  f"Needs PC: {original_res.get('needPc', True)}, " # Display needPc
                  f"Start: {details['start_time'].strftime('%Y-%m-%d %H:%M')}, "
                  f"End: {details['end_time'].strftime('%H:%M')}, Status: {status}")
    else:
        print("\nNo comprehensive solution found for all pending reservations after all strategies, even with random fallback.")